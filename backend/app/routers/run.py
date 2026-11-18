"""运行画布上的智能体：子进程执行 + SSE 流式回传。"""
from __future__ import annotations

import asyncio
import json
import os
import queue as thread_queue
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..config import PROJECTS_DIR, RUN_LOG_DIR, RUN_TIMEOUT
from ..constraints import validate as validate_graph
from ..db import get_conn, now_iso
from ..framework_env import interpreter as framework_interpreter
from ..framework_env import status as framework_status
from ..providers.bindings import env_bindings, resolve_runtime_providers
from ..runtime import warm
from ..schemas import RunRequest
from ..security import decrypt
from .canvases import _fetch, _node_key_env, resolve_runtime_model, save_canvas

router = APIRouter(prefix="/api/canvases", tags=["run"])

# 生成物会读的第三方模型 key：同属「不该由平台环境透传」的一类
_FOREIGN_KEY_ENV = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
                    "AZURE_OPENAI_API_KEY", "GOOGLE_API_KEY", "DASHSCOPE_API_KEY"}

EVENT_PREFIX = "@@EVENT@@"
# 热执行器出错一次就不再尝试（线程可能挂住，避免后续运行继续踩）
_WARM_BROKEN = False
DEPENDENCY_HINTS = {
    "langchain": ["langchain", "langchain_openai", "langgraph"],
    "autogen": ["autogen_agentchat", "autogen_ext"],
    "crewai": ["crewai"],
}


def _sse(obj: Dict[str, Any]) -> str:
    """给每个事件打上产生时间，前端显示的就是这条日志真正的时刻。"""
    evt = dict(obj)
    evt.setdefault("at", now_iso())
    return "data: " + json.dumps(evt, ensure_ascii=False, default=str) + "\n\n"


def _deps_status(framework: str) -> Dict[str, bool]:
    """依赖是否就绪。

    用隔离环境的框架（MetaGPT / Agno / SmolAgents / Semantic Kernel /
    OpenAI Agents）看自己那个 venv；其余看当前进程。
    """
    st = framework_status(framework)
    if st["isolated"]:
        return {framework: bool(st["ready"])}
    import importlib.util
    return {mod: importlib.util.find_spec(mod) is not None
            for mod in DEPENDENCY_HINTS.get(framework, [])}


@router.get("/{canvas_id}/env")
def env_status(canvas_id: str):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
    fw = row["framework"]
    deps = _deps_status(fw)
    cfg = resolve_runtime_model(row)
    st = framework_status(fw)
    return {
        "python": sys.version.split()[0],
        "executable": st.get("interpreter") or sys.executable,
        "framework": fw,
        "dependencies": deps,
        "all_dependencies_ready": all(deps.values()) if deps else True,
        "isolated": st.get("isolated", False),
        "env_path": st.get("path", ""),
        "env_ready": st.get("ready", True),
        "has_api_key": bool(cfg.get("api_key")),
        "model": cfg.get("model"),
        "base_url": cfg.get("base_url"),
        "node_runtime": True,
    }


@router.get("/{canvas_id}/runs")
def list_runs(canvas_id: str, limit: int = 20):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id,status,input,output,error,started_at,finished_at FROM runs "
            "WHERE canvas_id = ? ORDER BY started_at DESC LIMIT ?", (canvas_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# 运行输入附件：上传到项目目录的 inputs/ 下，运行时把路径交给画布
# --------------------------------------------------------------------------- #
MAX_INPUT_BYTES = 20 * 1024 * 1024
SAFE_INPUT_NAME = re.compile(r"[^\w.\-\u4e00-\u9fff]")


def _input_dir(row) -> Path:
    return PROJECTS_DIR / row["slug"] / "inputs"


def _safe_filename(name: str) -> str:
    base = Path(name or "file").name
    cleaned = SAFE_INPUT_NAME.sub("_", base).strip("._") or "file"
    return cleaned[:120]


@router.get("/{canvas_id}/inputs")
def list_inputs(canvas_id: str):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
    base = _input_dir(row)
    if not base.exists():
        return {"files": []}
    files = []
    for path in sorted(base.iterdir()):
        if path.is_file():
            files.append({"name": path.name, "path": f"inputs/{path.name}",
                          "size": path.stat().st_size})
    return {"files": files}


@router.post("/{canvas_id}/inputs")
async def upload_input(canvas_id: str, file: UploadFile = File(...)):
    """存一个附件到项目目录。返回相对路径，运行时原样传给子进程。"""
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
    name = _safe_filename(file.filename or "file")
    data = await file.read()
    if len(data) > MAX_INPUT_BYTES:
        raise HTTPException(400, f"文件超过 {MAX_INPUT_BYTES // 1024 // 1024}MB 上限")
    if not data:
        raise HTTPException(400, "文件是空的")

    base = _input_dir(row)
    base.mkdir(parents=True, exist_ok=True)
    target = base / name
    # 重名不覆盖，加后缀
    stem, suffix = target.stem, target.suffix
    index = 2
    while target.exists():
        target = base / f"{stem}_{index}{suffix}"
        index += 1
    target.write_bytes(data)
    return {"ok": True, "file": {"name": target.name,
                                 "path": f"inputs/{target.name}",
                                 "size": len(data)}}


@router.delete("/{canvas_id}/inputs")
def delete_input(canvas_id: str, path: str):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
    base = _input_dir(row).resolve()
    target = (PROJECTS_DIR / row["slug"] / path).resolve()
    # 只允许删 inputs/ 下的文件
    if base not in target.parents or not target.is_file():
        raise HTTPException(400, "只允许删除 inputs/ 下的附件")
    target.unlink()
    return {"ok": True}


@router.post("/{canvas_id}/run")
async def run_canvas(canvas_id: str, payload: RunRequest):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        graph_dict = json.loads(row["graph"] or "{}")
        cfg = resolve_runtime_model(row)
        slug = row["slug"]
        # 节点级 key：从 agent_models 表读出，只通过环境变量注入子进程
        node_models = conn.execute(
            "SELECT node_id, api_key_cipher FROM agent_models WHERE canvas_id = ?",
            (canvas_id,),
        ).fetchall()
        try:
            rules = json.loads(row["rules"] or "[]")
        except Exception:  # noqa: BLE001
            rules = []

    # 运行前先过一遍约束：error 级直接拦下，除非显式 force
    report = validate_graph(graph_dict, rules)
    if report["errors"] and not payload.force:
        raise HTTPException(409, detail={
            "message": f"画布有 {len(report['errors'])} 条约束未满足，已阻止运行",
            "violations": report["errors"],
            "warnings": report["warnings"],
        })

    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        project_dir, _files = save_canvas(row, graph_dict)

    run_id = uuid.uuid4().hex
    # 生成物读一堆 MINEAGENT_* 环境变量（模型、会话、可观测、安全、沙箱…），
    # 平台进程里残留任何一个都会悄悄覆盖画布配置（曾经就因为一个测试用的
    # MINEAGENT_API_KEY 让画布报 401）。所以这里整类清空，只按画布配置重新注入。
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("MINEAGENT_") and k not in _FOREIGN_KEY_ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if cfg.get("api_key"):
        env["MINEAGENT_API_KEY"] = cfg["api_key"]
    if cfg.get("base_url"):
        env["MINEAGENT_BASE_URL"] = cfg["base_url"]
    if cfg.get("model"):
        env["MINEAGENT_MODEL"] = cfg["model"]
    # 运行附件：路径清单交给子进程，节点可以用 ctx.files / ctx.read_file 读
    if payload.files:
        env["MINEAGENT_INPUT_FILES"] = json.dumps(payload.files, ensure_ascii=False)

    # 这个 key 到底从哪来：画布自带、全局设置、还是没有（排查 401 时最想知道的就是它）
    try:
        own_cfg = json.loads(row["model_config"] or "{}")
    except Exception:  # noqa: BLE001
        own_cfg = {}
    own_key = decrypt(own_cfg.get("api_key_cipher", "") or "") if own_cfg.get("api_key_cipher") else ""
    key_source = "canvas" if own_key else ("global" if cfg.get("api_key") else "none")

    node_keys = 0
    for nm in node_models:
        key = decrypt(nm["api_key_cipher"]) if nm["api_key_cipher"] else ""
        if key:
            env[_node_key_env(nm["node_id"])] = key
            node_keys += 1

    # 向量模型 / 向量库 / 数据源的密钥：同样只走环境变量，不落进项目文件
    for env_name, value in env_bindings(resolve_runtime_providers(canvas_id)).items():
        if value:
            env[env_name] = value

    # 附件清单也拼进 input：纯文本节点（LLM / 提示词）也能看到有哪些文件
    input_text = (payload.input or "").strip()
    if payload.files:
        listing = "\n".join(f"- {name}" for name in payload.files)
        input_text = (input_text + f"\n\n[附件]\n{listing}").strip()

    runner_path = os.path.join(project_dir, "runner.py")
    # 依赖齐全就跑项目里的 agent.py（真实框架代码）；
    # 缺依赖时降级到零依赖预览执行器 runner.py
    deps_ready = all(_deps_status(row["framework"]).values())
    agent_path = os.path.join(project_dir, "agent.py")
    entry_path = agent_path if deps_ready else runner_path
    run_mode = "native" if deps_ready else "preview"

    def _extract_final(lines: List[str]) -> str:
        text = "\n".join(lines).strip()
        marker = "最终结果"
        idx = text.rfind(marker)
        if idx >= 0:
            tail = text[idx:]
            parts = tail.split("\n", 1)
            return (parts[1] if len(parts) > 1 else tail).strip()
        return text

    async def stream() -> AsyncIterator[str]:
        global _WARM_BROKEN
        started = time.time()
        collected: List[Dict[str, Any]] = []
        final_output = ""
        status = "ok"
        errors: List[str] = []
        got_run_end = False
        log_lines: List[str] = []
        proc = None  # 只有走子进程时才有值

        yield _sse({"event": "prepared", "run_id": run_id, "canvas_id": canvas_id,
                    "project_dir": project_dir, "slug": slug,
                    "has_api_key": bool(cfg.get("api_key")),
                    "key_source": key_source,
                    "model": cfg.get("model"), "framework": row["framework"],
                    "run_mode": run_mode,
                    "entry": os.path.basename(entry_path)})

        def _handle_line(line: str):
            """子进程与热执行器共用的行解析：事件行转 SSE，普通行当日志。"""
            nonlocal got_run_end, final_output, status
            if not line or not line.strip():
                return None
            if line.startswith(EVENT_PREFIX):
                try:
                    evt = json.loads(line[len(EVENT_PREFIX):])
                except json.JSONDecodeError:
                    return None
                evt.setdefault("run_id", run_id)
                evt.setdefault("at", datetime.now().astimezone().isoformat(timespec="seconds"))
                if evt.get("event") != "token":
                    collected.append(evt)
                if evt.get("event") == "run_end":
                    got_run_end = True
                    final_output = evt.get("output", "") or ""
                    status = evt.get("status", "ok")
                if evt.get("event") == "error":
                    status = "error"
                    errors.append(str(evt.get("message", "")))
                return _sse(evt)
            if len(log_lines) < 2000:
                log_lines.append(line)
            return _sse({"event": "log", "level": "stdout", "message": line[:2000]})

        warm_ok = False

        async def _pump_warm():
            """热执行器：agent.py 只 import 一次，省掉每次 ~5s 的框架导入。"""
            nonlocal status, warm_ok
            handle = warm.WarmRun(Path(project_dir), Path(entry_path), input_text,
                                  {k: v for k, v in env.items()
                                   if k.startswith("MINEAGENT_")}).start()
            emitted = 0
            while True:
                if time.time() - started > RUN_TIMEOUT:
                    _WARM_BROKEN = True  # 线程可能在锁里，别再复用
                    status = "error"
                    errors.append("热执行超时")
                    yield _sse({"event": "error",
                                "message": f"运行超时（{RUN_TIMEOUT}s），已停止等待"})
                    warm_ok = True
                    return
                try:
                    item = handle.queue.get_nowait()
                except thread_queue.Empty:
                    await asyncio.sleep(0.01)
                    continue
                kind = item.get("kind")
                if kind in ("event", "log"):
                    line = (EVENT_PREFIX + json.dumps(item["event"], ensure_ascii=False)
                            if kind == "event" else (item.get("line") or ""))
                    chunk = _handle_line(line)
                    if chunk:
                        emitted += 1
                        yield chunk
                    continue
                if kind == "done":
                    if item.get("status") == "error":
                        status = "error"
                        errors.append(item.get("error") or "热执行失败")
                    warm_ok = True
                    return
                if emitted == 0:
                    warm_ok = False  # 一个事件都没出来：交给子进程，保持原行为
                    return
                _WARM_BROKEN = True
                status = "error"
                errors.append(item.get("error") or "热执行异常")
                warm_ok = True
                return

        async def _pump_subprocess(proc):
            assert proc.stdout is not None
            while True:
                if time.time() - started > RUN_TIMEOUT:
                    proc.kill()
                    yield _sse({"event": "error",
                                "message": f"运行超时（{RUN_TIMEOUT}s），已终止"})
                    return
                raw = await proc.stdout.readline()
                if not raw:
                    return
                chunk = _handle_line(raw.decode("utf-8", "replace").rstrip("\r\n"))
                if chunk:
                    yield chunk

        if run_mode == "native" and warm.ENABLED and not _WARM_BROKEN:
            try:
                async for chunk in _pump_warm():
                    yield chunk
                warm_ok = True
            except Exception as exc:  # noqa: BLE001
                errors.append(f"热执行不可用，回退子进程：{exc}")
                warm_ok = False

        if not warm_ok:
            try:
                runner_python = framework_interpreter(row["framework"]) or sys.executable
                proc = await asyncio.create_subprocess_exec(
                    str(runner_python), entry_path, "--input", input_text,
                    cwd=project_dir, env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except Exception as exc:  # noqa: BLE001
                yield _sse({"event": "error", "message": f"启动执行进程失败：{exc}"})
                yield _sse({"event": "run_end", "status": "error", "message": str(exc),
                            "output": "", "duration_ms": 0})
                return
            try:
                async for chunk in _pump_subprocess(proc):
                    yield chunk
                await proc.wait()
            except asyncio.CancelledError:
                proc.kill()
                raise
            finally:
                if proc.returncode is None:
                    proc.kill()

        duration = int((time.time() - started) * 1000)
        # 子进程没发 run_end（纯打印输出）时，从普通输出里提取最终结果兜底
        if not got_run_end:
            if run_mode == "native":
                final_output = _extract_final(log_lines)
                if proc is not None and proc.returncode not in (0, None):
                    status = "error"
                    if not errors:
                        errors.append(_extract_final(log_lines)[-500:] or "进程异常退出")
            yield _sse({"event": "run_end", "status": status,
                        "output": final_output, "duration_ms": duration,
                        "run_mode": run_mode})
        if status == "ok" and not final_output and collected:
            for evt in reversed(collected):
                if evt.get("event") == "run_end":
                    final_output = evt.get("output", "") or ""
                    break

        # 落库
        try:
            RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
            (RUN_LOG_DIR / f"{run_id}.jsonl").write_text(
                "\n".join(json.dumps(e, ensure_ascii=False, default=str) for e in collected),
                encoding="utf-8")
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO runs(id,canvas_id,status,input,output,error,started_at,finished_at)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (run_id, canvas_id, status, input_text, final_output,
                     "; ".join(errors)[:2000], now_iso(), now_iso()),
                )
        except Exception:  # noqa: BLE001
            pass

        if got_run_end:
            # 事件流里已经推过子进程的 run_end，这里只补最终状态（不再重复一条）
            return

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
