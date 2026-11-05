"""MineAgent 项目运行时 SDK。

这段代码会被复制到每一个画布项目目录（projects/<画布>/runtime_sdk.py），
画布上的每个节点就是 `nodes/*.py` 里的一个 `run(ctx)` 函数。

它零第三方依赖，只用标准库，所以只要本机有 Python 就能跑；
装了对应框架（langgraph / autogen / crewai）时，agent.py 会走框架原生实现，
否则 runner.py 用内置解释器执行同一批节点函数。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

EVENT_PREFIX = "@@EVENT@@"
EVENT_STREAM = sys.stdout

PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_DIR / "config.json"


# --------------------------------------------------------------------------- #
# 事件输出
# --------------------------------------------------------------------------- #
class _SafeStream:
    """保证事件不因为编码问题炸掉。"""

    def write(self, s: str) -> int:  # pragma: no cover
        try:
            return EVENT_STREAM.write(s)
        except UnicodeEncodeError:
            return EVENT_STREAM.write(s.encode("utf-8", "replace").decode("utf-8"))
        return 0

    def flush(self) -> None:  # pragma: no cover
        EVENT_STREAM.flush()


_out = _SafeStream()


def emit_event(event: Dict[str, Any]) -> None:
    _out.write(EVENT_PREFIX + json.dumps(event, ensure_ascii=False, default=str) + "\n")
    _out.flush()


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def load_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    # 项目内 .env（导出后独立运行用）
    env_file = PROJECT_DIR / ".env"
    file_env: Dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            file_env[k.strip()] = v.strip().strip('"').strip("'")
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    cfg["api_key"] = (
        os.environ.get("MINEAGENT_API_KEY")
        or file_env.get("MINEAGENT_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or file_env.get("OPENAI_API_KEY")
        or ""
    )
    cfg["base_url"] = os.environ.get("MINEAGENT_BASE_URL") or cfg.get("base_url") or cfg["base_url"]
    cfg["model"] = os.environ.get("MINEAGENT_MODEL") or cfg.get("model") or cfg["model"]
    return cfg


# --------------------------------------------------------------------------- #
# HTTP / LLM
# --------------------------------------------------------------------------- #
def _normalize_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        base = "https://api.openai.com/v1"
    if base.endswith("/chat/completions"):
        return base
    if not base.endswith("/v1") and "/v1" not in base:
        base += "/v1"
    return base + "/chat/completions"


def _open(req: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout)


def http_json(method: str, url: str, headers: Optional[Dict[str, str]] = None,
              payload: Any = None, timeout: float = 60.0) -> Any:
    data = None
    hdrs = {"User-Agent": "MineAgent/1.0", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
    with _open(req, timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw}


def chat_completion(messages: List[Dict[str, str]], cfg: Optional[Dict[str, Any]] = None,
                    model: Optional[str] = None, temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None, timeout: float = 180.0) -> str:
    cfg = cfg or load_config()
    if not cfg.get("api_key"):
        raise RuntimeError(
            "缺少模型 API Key：请在网页右上角「用户中心」或画布设置里配置，"
            "或在项目目录创建 .env 写入 MINEAGENT_API_KEY=sk-xxx"
        )
    payload = {
        "model": model or cfg.get("model"),
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3) if temperature is None else temperature,
        "max_tokens": max_tokens or cfg.get("max_tokens", 2048),
        "stream": False,
    }
    resp = http_json("POST", _normalize_url(cfg.get("base_url", "")),
                     headers={"Authorization": f"Bearer {cfg['api_key']}"},
                     payload=payload, timeout=timeout)
    try:
        return resp["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"模型返回格式异常：{str(resp)[:400]}")


def chat_stream(messages: List[Dict[str, str]], cfg: Optional[Dict[str, Any]] = None,
                model: Optional[str] = None, on_token: Optional[Callable[[str], None]] = None,
                timeout: float = 300.0) -> str:
    cfg = cfg or load_config()
    if not cfg.get("api_key"):
        raise RuntimeError("缺少模型 API Key，请先在用户中心或画布设置里配置")
    payload = {
        "model": model or cfg.get("model"),
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": cfg.get("max_tokens", 2048),
        "stream": True,
    }
    req = urllib.request.Request(
        _normalize_url(cfg.get("base_url", "")),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg['api_key']}",
                 "Accept": "text/event-stream"},
        method="POST",
    )
    chunks: List[str] = []
    with _open(req, timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
                delta = obj["choices"][0]["delta"].get("content") or ""
            except Exception:
                continue
            if delta:
                chunks.append(delta)
                if on_token:
                    on_token(delta)
    return "".join(chunks)


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    for pattern in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pattern, text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                continue
    return None


# --------------------------------------------------------------------------- #
# 轻量向量（无外部依赖，离线可用）
# --------------------------------------------------------------------------- #
def local_embed(text: str, dim: int = 256) -> List[float]:
    vec = [0.0] * dim
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower())
    for tok in tokens:
        for gram in (tok, tok[:3], tok[-3:]):
            h = 0
            for ch in gram:
                h = (h * 131 + ord(ch)) & 0xFFFFFFFF
            vec[h % dim] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a, b = list(a), list(b)
    return sum(x * y for x, y in zip(a, b))


# --------------------------------------------------------------------------- #
# 节点上下文
# --------------------------------------------------------------------------- #
@dataclass
class ToolSpec:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "传入工具的参数"}},
        "required": ["query"],
    })

    def schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": re.sub(r"[^\w]", "_", self.name)[:64],
                "description": self.description[:512],
                "parameters": self.parameters,
            },
        }

    def __call__(self, **kwargs):
        return self.func(**kwargs)


class NodeContext:
    """节点函数拿到的全部能力都在这里。"""

    def __init__(self, node_id: str, node_name: str, kind: str, params: Dict[str, Any],
                 payload: Any, state: Dict[str, Any], run_id: str = ""):
        self.node_id = node_id
        self.node_name = node_name
        self.kind = kind
        self.params = params or {}
        self.input = payload
        self.state = state
        self.run_id = run_id
        self.tools: List[ToolSpec] = []
        self.config = load_config()

    # ---- 输入 ----
    @property
    def text(self) -> str:
        if self.input is None:
            return ""
        if isinstance(self.input, str):
            return self.input
        if isinstance(self.input, (dict, list)):
            for key in ("text", "answer", "output", "content", "result", "formatted"):
                if isinstance(self.input, dict) and isinstance(self.input.get(key), str):
                    return self.input[key]
            return json.dumps(self.input, ensure_ascii=False, indent=2)
        return str(self.input)

    # ---- 日志与事件 ----
    def log(self, message: str, level: str = "info") -> None:
        emit_event({"event": "log", "level": level, "node": self.node_id,
                    "name": self.node_name, "message": str(message)[:4000]})

    def emit(self, kind: str, payload: Any) -> None:
        emit_event({"event": "custom", "type": kind, "node": self.node_id,
                    "name": self.node_name, "payload": payload})

    def route(self, branch: str) -> None:
        self.state["__branch__"] = branch

    # ---- 模型 ----
    def llm(self, prompt: str, system: Optional[str] = None, model: Optional[str] = None,
            temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        messages: List[Dict[str, str]] = []
        sys_prompt = system or self.state.get("system_prompt")
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": str(prompt)})
        return chat_completion(messages, self.config, model=model, temperature=temperature,
                               max_tokens=max_tokens)

    def llm_stream(self, prompt: str, system: Optional[str] = None, model: Optional[str] = None) -> str:
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": str(prompt)})
        return chat_stream(messages, self.config, model=model,
                           on_token=lambda t: emit_event({"event": "token", "node": self.node_id,
                                                          "name": self.node_name, "text": t}))

    def json_prompt(self, instruction: str, schema: Any, context: Any = "") -> Any:
        prompt = (
            f"{instruction}\n\n## 待处理内容\n{context if context != '' else self.text}\n\n"
            f"## 输出格式（严格 JSON，不要额外解释）\n{json.dumps(schema, ensure_ascii=False)}"
        )
        raw = self.llm(prompt, system="你只输出符合要求结构的 JSON。")
        data = _extract_json(raw)
        return schema if data is None else data

    def agent(self, task: str, tools: Optional[List[ToolSpec]] = None,
              system: Optional[str] = None, max_steps: int = 6) -> str:
        tools = tools if tools is not None else self.tools
        base_system = system or "你是一个能自主使用工具的智能体。"
        tool_desc = "\n".join(f"- {t.name}: {t.description}" for t in tools) or "（无可用工具）"
        transcript: List[str] = []
        scratch = task
        for step in range(1, max_steps + 1):
            emit_event({"event": "agent_step", "node": self.node_id, "step": step,
                        "max_steps": max_steps})
            prompt = (
                f"{scratch}\n\n## 可用工具\n{tool_desc}\n\n"
                f"## 已执行步骤\n{chr(10).join(transcript) or '（暂无）'}\n\n"
                "请决定下一步。只输出一个 JSON：\n"
                '{"thought": "...", "action": "工具名", "action_input": {"query": "..."}}\n'
                '如果已经可以给出最终答案，输出：{"thought": "...", "final_answer": "..."}'
            )
            raw = self.llm(prompt, system=base_system)
            decision = _extract_json(raw) or {}
            if not isinstance(decision, dict):
                return raw
            if decision.get("final_answer"):
                return str(decision["final_answer"])
            action = decision.get("action")
            args = decision.get("action_input") or {}
            tool = next((t for t in tools if re.sub(r"[^\w]", "_", t.name) ==
                         re.sub(r"[^\w]", "_", str(action))), None)
            if tool is None:
                transcript.append(f"第{step}步：调用未知工具 {action}，跳过")
                continue
            if not isinstance(args, dict):
                args = {"query": str(args)}
            try:
                result = tool(**args)
            except Exception as exc:  # noqa: BLE001
                result = f"工具执行失败：{exc}"
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            transcript.append(f"第{step}步：{tool.name}({json.dumps(args, ensure_ascii=False)}) -> {text[:600]}")
            emit_event({"event": "tool_call", "node": self.node_id, "tool": tool.name,
                        "args": args, "result": text[:2000]})
            self.state.setdefault("observations", []).append(
                {"node": self.node_name, "summary": text[:400], "raw": text})
            scratch = f"{task}\n\n（上一轮工具结果：{text[:800]}）"
        return self.llm(
            f"{task}\n\n## 执行记录\n{chr(10).join(transcript)}\n\n请给出最终答案。",
            system=base_system,
        )

    # ---- 外部能力 ----
    def http(self, method: str, url: str, headers: Optional[Dict[str, str]] = None,
             params: Optional[Dict[str, Any]] = None, json: Any = None,
             data: Any = None, timeout: float = 60.0) -> Any:
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return http_json(method, url, headers=headers, payload=json if json is not None else data,
                         timeout=timeout)

    def fetch_text(self, url: str, limit: int = 8000) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 MineAgent/1.0"})
        with _open(req, 30) as resp:
            html = resp.read().decode("utf-8", "replace")
        html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    def search(self, query: str, limit: int = 5) -> str:
        try:
            url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(query)
            page = self.fetch_text(url, limit=20000)
            return page[:4000]
        except Exception as exc:  # noqa: BLE001
            self.log(f"联网搜索失败：{exc}", "warn")
            return ""

    def skill(self, name: str = "", inline: str = "") -> str:
        if inline and inline.strip():
            return inline.strip()
        if name:
            for base in (PROJECT_DIR / "skills", PROJECT_DIR, PROJECT_DIR / "skills_import"):
                p = base / name
                if p.exists() and p.is_file():
                    return p.read_text(encoding="utf-8", errors="replace")
        return "（未找到技能文件，请填写 skill.md 内容或文件名）"

    # ---- 记忆 ----
    def remember(self, key: str, value: Any, long_term: bool = False) -> None:
        self.state.setdefault("memory", {})[key] = value
        if long_term:
            store = _open_store()
            store.execute(
                "CREATE TABLE IF NOT EXISTS memory(key TEXT, value TEXT, ts REAL)",
                (),
            )
            store.execute("INSERT INTO memory VALUES(?,?,?)",
                          (key, json.dumps(value, ensure_ascii=False, default=str), time.time()))
            store.commit()

    def recall(self, key: str, default: Any = None) -> Any:
        if key in self.state.get("memory", {}):
            return self.state["memory"][key]
        try:
            store = _open_store()
            store.execute("CREATE TABLE IF NOT EXISTS memory(key TEXT, value TEXT, ts REAL)", ())
            rows = store.execute(
                "SELECT value FROM memory WHERE key=? ORDER BY ts DESC LIMIT 1", (key,)
            ).fetchall()
            store.commit()
            if rows:
                return json.loads(rows[0][0])
        except Exception:
            pass
        return default

    def history(self, key: str = "conversation") -> List[Any]:
        val = self.recall(key, [])
        if isinstance(val, list):
            return val
        return [val] if val else []

    # ---- 向量 ----
    def embed(self, text: str) -> List[float]:
        return local_embed(text)

    def retrieve(self, query: str, top_k: int = 4, folders: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        folders = folders or ["skills", "docs", "outputs"]
        qv = local_embed(query)
        scored: List[Dict[str, Any]] = []
        for folder in folders:
            base = PROJECT_DIR / folder
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".db", ".pyc"}:
                    continue
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for i, chunk in enumerate(_chunk(content, 600)):
                    scored.append({
                        "source": str(path.relative_to(PROJECT_DIR)).replace("\\", "/"),
                        "chunk": chunk,
                        "score": round(cosine(qv, local_embed(chunk)), 4),
                        "index": i,
                    })
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def vector_upsert(self, text: str) -> Dict[str, Any]:
        store = _open_store()
        store.execute("CREATE TABLE IF NOT EXISTS vectors(id TEXT, text TEXT, vec TEXT)", ())
        vid = f"{self.node_id}-{int(time.time() * 1000)}"
        store.execute("INSERT INTO vectors VALUES(?,?,?)",
                      (vid, text, json.dumps(local_embed(text))))
        store.commit()
        return {"id": vid, "stored": True}

    def vector_search(self, query: str, top_k: int = 4) -> List[Dict[str, Any]]:
        store = _open_store()
        store.execute("CREATE TABLE IF NOT EXISTS vectors(id TEXT, text TEXT, vec TEXT)", ())
        qv = local_embed(query)
        out = []
        for vid, text, vec in store.execute("SELECT id, text, vec FROM vectors").fetchall():
            out.append({"id": vid, "text": text, "score": round(cosine(qv, json.loads(vec)), 4)})
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:top_k]

    # ---- 执行类 ----
    def exec_python(self, code: str, timeout: float = 30.0) -> Dict[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snippet.py"
            path.write_text(code, encoding="utf-8")
            try:
                proc = subprocess.run([sys.executable, str(path)], capture_output=True,
                                      text=True, timeout=timeout, cwd=str(PROJECT_DIR),
                                      encoding="utf-8", errors="replace")
                return {"stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}
            except subprocess.TimeoutExpired:
                return {"stdout": "", "stderr": f"执行超时（{timeout}s）"}

    def shell(self, command: str, timeout: float = 60.0) -> Dict[str, str]:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True,
                              timeout=timeout, cwd=str(PROJECT_DIR),
                              encoding="utf-8", errors="replace")
        return {"code": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}

    def read_file(self, rel_path: str) -> str:
        p = (PROJECT_DIR / rel_path).resolve()
        if PROJECT_DIR not in p.parents and p != PROJECT_DIR:
            raise PermissionError("只能访问项目目录内的文件")
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

    def write_file(self, rel_path: str, content: str) -> str:
        p = (PROJECT_DIR / rel_path).resolve()
        if PROJECT_DIR not in p.parents and p != PROJECT_DIR:
            raise PermissionError("只能写入项目目录内的文件")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if isinstance(content, str) else str(content), encoding="utf-8")
        return str(p.relative_to(PROJECT_DIR)).replace("\\", "/")

    def query_sql(self, sql: str) -> List[Dict[str, Any]]:
        if not re.match(r"^\s*(select|with)\b", sql, re.I):
            raise PermissionError("只允许只读查询（SELECT / WITH）")
        store = _open_store()
        try:
            cur = store.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, row)) for row in cur.fetchall()][:500]
        finally:
            store.close()

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, min(float(seconds), 30.0)))

    def validate(self, data: Any, schema: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        if not isinstance(schema, dict) or not schema:
            return errors
        for key, expected in schema.items():
            if isinstance(data, dict):
                if key not in data:
                    errors.append(f"缺少字段 {key}")
                elif isinstance(expected, list) and not isinstance(data[key], list):
                    errors.append(f"字段 {key} 应为数组")
                elif isinstance(expected, dict) and not isinstance(data[key], dict):
                    errors.append(f"字段 {key} 应为对象")
        return errors

    def ask_human(self, question: str, default: str = "approve") -> str:
        self.emit("human_approval", {"question": question[:2000], "auto": default})
        self.log(f"需要人工审批（无交互环境，按默认值 {default} 处理）", "warn")
        return default

    def run_subgraph(self, project: str, payload: Any) -> Any:
        target = (PROJECT_DIR.parent / project).resolve()
        if not (target / "runner.py").exists():
            raise FileNotFoundError(f"找不到子图项目：{project}")
        proc = subprocess.run(
            [sys.executable, str(target / "runner.py"), "--input",
             payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, timeout=600, cwd=str(target),
            encoding="utf-8", errors="replace",
        )
        for line in (proc.stdout or "").splitlines():
            if line.startswith(EVENT_PREFIX):
                try:
                    evt = json.loads(line[len(EVENT_PREFIX):])
                except Exception:
                    continue
                if evt.get("event") == "run_end":
                    return evt.get("output", "")
        return proc.stdout[-2000:]

    # ---- 框架桥接（装了对应依赖就走原生实现，没装则降级为通用实现） ----
    def _framework_ready(self, module: str) -> bool:
        try:
            __import__(module)
            return True
        except Exception:
            return False

    def autogen_assistant(self, name: str, system_message: str, task: str) -> str:
        try:
            from autogen_agentchat.agents import AssistantAgent  # type: ignore
            from autogen_ext.models.openai import OpenAIChatCompletionClient  # type: ignore
            import asyncio

            client = OpenAIChatCompletionClient(
                model=self.config["model"], base_url=self.config.get("base_url"),
                api_key=self.config["api_key"],
                model_info={"vision": False, "function_calling": True, "json_output": True,
                            "family": "unknown", "structured_output": False},
            )

            async def _run():
                agent = AssistantAgent(name=name, model_client=client,
                                       system_message=system_message)
                res = await agent.run(task=task)
                await client.close()
                return getattr(res, "messages", [])[-1].content if getattr(res, "messages", []) else ""

            return asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.log(f"AutoGen 原生调用不可用（{exc}），降级为通用 LLM 调用", "warn")
            return self.llm(task, system=system_message)

    def autogen_user_proxy(self, name: str, task: str, human_input_mode: str = "NEVER") -> str:
        self.log(f"UserProxy({name}) 转交任务，human_input_mode={human_input_mode}")
        return task

    def autogen_group_chat(self, agents: List[str], task: str, max_round: int = 6) -> str:
        try:
            from autogen_agentchat.agents import AssistantAgent  # type: ignore
            from autogen_agentchat.teams import RoundRobinGroupChat  # type: ignore
            from autogen_ext.models.openai import OpenAIChatCompletionClient  # type: ignore
            import asyncio

            client = OpenAIChatCompletionClient(
                model=self.config["model"], base_url=self.config.get("base_url"),
                api_key=self.config["api_key"],
                model_info={"vision": False, "function_calling": True, "json_output": True,
                            "family": "unknown", "structured_output": False},
            )

            async def _run():
                members = [AssistantAgent(name=a, model_client=client,
                                          system_message=f"你是 {a}，负责该角色的工作。") for a in agents]
                team = RoundRobinGroupChat(members, max_turns=max_round)
                res = await team.run(task=task)
                await client.close()
                return getattr(res, "messages", [])[-1].content if getattr(res, "messages", []) else ""

            return asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.log(f"AutoGen GroupChat 不可用（{exc}），降级为多角色轮询", "warn")
            transcript = []
            for a in agents:
                transcript.append(f"{a}: {self.llm(task, system=f'你是 {a}，从你的角色出发给出意见。')}")
            return self.llm(f"讨论：{transcript}\n\n综合输出结论。", system="你是主持人。")

    def crewai_agent(self, role: str, goal: str, backstory: str, task: str) -> str:
        self.state.setdefault("crewai_agents", []).append(
            {"role": role, "goal": goal, "backstory": backstory})
        return self.llm(task or goal, system=f"你是{role}。目标：{goal}。背景：{backstory}")

    def crewai_task(self, description: str, expected_output: str, agent: str = "") -> str:
        self.state.setdefault("crewai_tasks", []).append(
            {"description": description, "expected_output": expected_output, "agent": agent})
        return self.llm(
            f"任务：{description}\n期望产出：{expected_output}\n输入：{self.text}",
            system=f"你是{agent or '执行者'}，只输出任务产出。")

    def crewai_crew(self, agents: List[Any], tasks: List[Any], process: str, task: str) -> str:
        ctx_agents = agents or self.state.get("crewai_agents", [])
        ctx_tasks = tasks or self.state.get("crewai_tasks", [])
        transcript = []
        for t in ctx_tasks:
            desc = t.get("description") if isinstance(t, dict) else str(t)
            transcript.append(self.llm(f"{desc}\n原始输入：{task}", system="你是 Crew 中的执行者。"))
        return self.llm(
            f"团队产出：{transcript}\n请汇总为最终交付物。", system="你是 Crew Manager。")

    def crewai_tool(self, name: str, description: str, payload: Any) -> Any:
        return {"tool": name, "description": description, "payload": payload,
                "result": f"（{name} 工具占位实现，请在节点代码里替换为真实逻辑）"}

    def mcp_call(self, server: str, tool: str, args: Dict[str, Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": tool, "arguments": args}}
        return http_json("POST", server, headers={"Content-Type": "application/json"},
                         payload=payload, timeout=120)


def _chunk(text: str, size: int) -> List[str]:
    text = text.strip()
    if not text:
        return []
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf = [], ""
    for p in paragraphs:
        if len(buf) + len(p) <= size:
            buf += ("\n\n" if buf else "") + p
        else:
            if buf:
                chunks.append(buf)
            buf = p[:size]
    if buf:
        chunks.append(buf)
    return chunks[:50]


_STORE = None


def _open_store():
    global _STORE
    import sqlite3
    if _STORE is None:
        _STORE = sqlite3.connect(PROJECT_DIR / ".store.db")
    return _STORE
