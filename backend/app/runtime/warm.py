"""进程内热执行器：agent.py 只 import 一次，后续运行省掉 langchain/langgraph 的导入开销。

背景：平台每次点「运行」都是 `create_subprocess_exec(python, agent.py)` 起一个新进程，
而 `import agent` 本身要 4.9s（langchain + langgraph）。画布不变时这 5 秒是纯浪费。

约定与边界：
- 缓存键 = 入口文件绝对路径；失效条件 = 文件 mtime/size 变化、或运行环境变量（key/base/model）变化；
- 运行串行化：`sys.stdout` 重定向是进程级状态，不能并发捕获；
- 只用于 native 模式的 agent.py；预览执行器（runner.py，零依赖）继续走子进程；
- 任何异常都往上抛，由调用方回退到子进程执行——热执行器只负责「快」，不负责「兜底」。
"""
from __future__ import annotations

import contextlib
import importlib.util
import inspect
import io
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

EVENT_PREFIX = "@@EVENT@@"
# 这些环境变量会改变 agent 的模型/密钥绑定，变了就必须重新 import
ENV_KEYS = (
    "MINEAGENT_API_KEY", "MINEAGENT_BASE_URL", "MINEAGENT_MODEL",
    "MINEAGENT_INPUT_FILES", "MINEAGENT_SESSION_STORE",
)
CACHE: Dict[str, Tuple[str, Any]] = {}
LOCK = threading.Lock()


def _signature(entry: Path, env: Dict[str, str]) -> str:
    stat = entry.stat()
    env_sig = "|".join(f"{k}={env.get(k, '')}" for k in ENV_KEYS)
    return f"{stat.st_mtime_ns}:{stat.st_size}:{env_sig}"


def _load(project_dir: Path, entry: Path, env: Dict[str, str]):
    key = str(entry)
    sig = _signature(entry, env)
    hit = CACHE.get(key)
    if hit and hit[0] == sig:
        return hit[1]

    name = f"_warm_{abs(hash(key)) % 10**8:08d}"
    spec = importlib.util.spec_from_file_location(name, entry)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载入口：{entry}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    inserted = str(project_dir) not in sys.path
    if inserted:
        sys.path.insert(0, str(project_dir))
    previous = {k: os.environ.get(k) for k in ENV_KEYS}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    cwd = os.getcwd()
    try:
        os.chdir(project_dir)  # 节点代码里可能有相对路径读取
        spec.loader.exec_module(module)
    finally:
        os.chdir(cwd)
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if inserted:
            try:
                sys.path.remove(str(project_dir))
            except ValueError:
                pass
    CACHE[key] = (sig, module)
    return module


class _Sink(io.TextIOBase):
    """把 agent 打到 stdout 的行分流成事件 / 普通日志，实时喂给调用方。"""

    def __init__(self, on_event: Callable[[Dict[str, Any]], None],
                 on_log: Callable[[str], None], buffers: Dict[str, List[str]]):
        self.on_event = on_event
        self.on_log = on_log
        self.buffers = buffers
        self._pending = ""

    def write(self, text: str) -> int:  # type: ignore[override]
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._emit_line(line)
        return len(text)

    def flush(self) -> None:  # type: ignore[override]
        if self._pending:
            self._emit_line(self._pending)
            self._pending = ""

    def _emit_line(self, line: str) -> None:
        line = line.rstrip("\r")
        if line.startswith(EVENT_PREFIX):
            raw = line[len(EVENT_PREFIX):].strip()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                self.buffers["log"].append(line)
                self.on_log(line)
                return
            self.buffers["events"].append(payload)
            self.on_event(payload)
            return
        self.buffers["log"].append(line)
        if line.strip():
            self.on_log(line)


def run(project_dir: Path, entry: Path, input_text: str, env: Dict[str, str],
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """在锁内跑一次；返回 events / logs / status / duration_ms / error。"""
    project_dir = Path(project_dir).resolve()
    entry = Path(entry).resolve()
    env = {k: v for k, v in (env or {}).items() if k in ENV_KEYS}
    buffers: Dict[str, List[str]] = {"events": [], "log": []}
    sink = _Sink(on_event or (lambda _e: None), on_log or (lambda _l: None), buffers)
    started = time.time()
    result: Dict[str, Any] = {"status": "ok", "error": "", "duration_ms": 0}
    # 拿不到锁说明上一次热执行还没结束（例如客户端断开但线程仍在跑）：
    # 直接抛出，让调用方回退到可杀死的子进程，而不是无限排队
    if not LOCK.acquire(timeout=90):
        raise RuntimeError("热执行器忙：上一次运行尚未结束，已回退子进程")
    try:
        previous = {k: os.environ.get(k) for k in ENV_KEYS}
        cwd = os.getcwd()
        argv = list(sys.argv)
        try:
            module = _load(project_dir, entry, env)
            # 节点代码会在函数体内 `from runtime_sdk import ...`，整个运行期间都要能找到
            if str(project_dir) not in sys.path:
                sys.path.insert(0, str(project_dir))
            os.environ.update({k: v for k, v in env.items() if v is not None})
            os.chdir(project_dir)
            sys.argv = [str(entry), "--input", input_text]
            # agent.py 的 main 可能收 user_input（位置参数），也可能是无参入口
            params = [p for p in inspect.signature(module.main).parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                      and p.default is p.empty]
            with contextlib.redirect_stdout(sink):
                module.main(input_text) if params else module.main()
            sink.flush()
        except SystemExit as exc:  # agent.main() 正常返回走 SystemExit
            if exc.code not in (0, None):
                result["status"] = "error"
                result["error"] = f"exit {exc.code}"
        except BaseException as exc:  # noqa: BLE001
            result["status"] = "error"
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            sys.argv = argv
            os.chdir(cwd)
            try:
                sys.path.remove(str(project_dir))
            except ValueError:
                pass
            for k, v in previous.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            result["duration_ms"] = int((time.time() - started) * 1000)
    finally:
        LOCK.release()
    result["events"] = buffers["events"]
    result["logs"] = buffers["log"]
    return result


ENABLED = os.environ.get("MINEAGENT_WARM", "1") != "0"


class WarmRun:
    """一次热执行的句柄：queue 里依次是 event / log / done / failed。"""

    def __init__(self, project_dir: Path, entry: Path, input_text: str, env: Dict[str, str]):
        self.queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.thread = threading.Thread(
            target=self._worker, args=(project_dir, entry, input_text, env),
            name="warm-run", daemon=True,
        )

    def _worker(self, project_dir: Path, entry: Path, input_text: str,
                env: Dict[str, str]) -> None:
        def push(event: Dict[str, Any]) -> None:
            self.queue.put({"kind": "event", "event": event})

        def log(line: str) -> None:
            self.queue.put({"kind": "log", "line": line})

        try:
            res = run(project_dir, entry, input_text, env, on_event=push, on_log=log)
            self.queue.put({"kind": "done", **res})
        except BaseException as exc:  # noqa: BLE001
            self.queue.put({"kind": "failed", "error": f"{type(exc).__name__}: {exc}"})

    def start(self) -> "WarmRun":
        self.thread.start()
        return self


def run_in_background(project_dir: Path, entry: Path, input_text: str, env: Dict[str, str],
                      out: "queue.Queue[Dict[str, Any]]") -> threading.Thread:
    """给 SSE 用：在后台线程跑，把事件逐条塞进 queue，最后塞一条 __done__。"""

    def worker() -> None:
        def push(event: Dict[str, Any]) -> None:
            out.put({"kind": "event", "event": event})

        def log(line: str) -> None:
            out.put({"kind": "log", "line": line})

        try:
            res = run(project_dir, entry, input_text, env, on_event=push, on_log=log)
            out.put({"kind": "done", **res})
        except BaseException as exc:  # noqa: BLE001
            out.put({"kind": "failed", "error": f"{type(exc).__name__}: {exc}"})

    thread = threading.Thread(target=worker, name="warm-run", daemon=True)
    thread.start()
    return thread


def warm_ready() -> bool:
    """热执行器只在主进程里可用；没有缓存时第一次仍会付 import 成本。"""
    return True


def cached_entries() -> List[str]:
    return sorted(CACHE)
