"""把画布级「服务设置」编译成项目里的生产化文件。

生成物（只对可运行的框架）：
- server.py     FastAPI 服务入口：/chat、/chat/stream、/health、/ready、/metrics
- settings.py   全部配置走环境变量
- telemetry.py  结构化日志 + 轻量 metrics
- checkpoint.py 会话持久化（SQLite / Postgres）
- Dockerfile / docker-compose.yml / .github/workflows/ci.yml / tests/
"""
from __future__ import annotations

import json
from typing import Any, Dict

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "entry": {"mode": "both", "path": "/chat", "auth": "none", "cors": "*"},
    "session": {"store": "sqlite", "max_turns": 20, "ttl_minutes": 1440},
    "runtime": {"max_concurrency": 4, "queue_limit": 100, "run_timeout_s": 600, "resume": False},
    "observability": {"log_level": "info", "json_logs": True, "metrics": True,
                      "trace_sample": 1, "budget_usd": 0},
    "security": {"sandbox": "restricted", "guardrail": "log", "pii": False, "audit": True},
}


def merge_service(raw: Any) -> Dict[str, Dict[str, Any]]:
    raw = raw or {}
    out: Dict[str, Dict[str, Any]] = {}
    for group, defaults in DEFAULTS.items():
        merged = dict(defaults)
        if isinstance(raw.get(group), dict):
            merged.update({k: v for k, v in raw[group].items() if k in defaults})
        out[group] = merged
    return out


def _py(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_settings(spec: Dict[str, Any], svc: Dict[str, Dict[str, Any]]) -> str:
    e, s, r, o, sec = (svc["entry"], svc["session"], svc["runtime"],
                       svc["observability"], svc["security"])
    return f'''"""服务配置：全部从环境变量读，改 .env 即可。"""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {{"1", "true", "yes", "on"}}


class Settings:
    project_name = {json.dumps(spec.get("name") or "agent", ensure_ascii=False)}
    entry_mode = os.environ.get("MINEAGENT_ENTRY_MODE", {_py(e["mode"])})
    entry_path = os.environ.get("MINEAGENT_ENTRY_PATH", {_py(e["path"])})
    auth = os.environ.get("MINEAGENT_AUTH", {_py(e["auth"])})
    api_key = os.environ.get("MINEAGENT_SERVICE_KEY", "")
    cors = os.environ.get("MINEAGENT_CORS", {_py(e["cors"])})
    session_store = os.environ.get("MINEAGENT_SESSION_STORE", {_py(s["store"])})
    max_turns = _int("MINEAGENT_MAX_TURNS", {int(s["max_turns"])})
    session_ttl = _int("MINEAGENT_SESSION_TTL", {int(s["ttl_minutes"])})
    max_concurrency = _int("MINEAGENT_MAX_CONCURRENCY", {int(r["max_concurrency"])})
    queue_limit = _int("MINEAGENT_QUEUE_LIMIT", {int(r["queue_limit"])})
    run_timeout_s = _int("MINEAGENT_RUN_TIMEOUT", {int(r["run_timeout_s"])})
    resume = _bool("MINEAGENT_RESUME", {_py(r["resume"])})
    log_level = os.environ.get("MINEAGENT_LOG_LEVEL", {_py(o["log_level"])})
    json_logs = _bool("MINEAGENT_JSON_LOGS", {_py(o["json_logs"])})
    metrics_on = _bool("MINEAGENT_METRICS", {_py(o["metrics"])})
    trace_sample = _float("MINEAGENT_TRACE_SAMPLE", {float(o["trace_sample"])})
    budget_usd = _float("MINEAGENT_BUDGET_USD", {float(o["budget_usd"])})
    sandbox = os.environ.get("MINEAGENT_SANDBOX", {_py(sec["sandbox"])})
    guardrail = os.environ.get("MINEAGENT_GUARDRAIL", {_py(sec["guardrail"])})
    pii = _bool("MINEAGENT_PII", {_py(sec["pii"])})
    audit = _bool("MINEAGENT_AUDIT", {_py(sec["audit"])})


settings = Settings()
'''


def render_telemetry() -> str:
    return '''"""结构化日志 + 轻量 metrics（零依赖，够用就好）。"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict


_LOG = logging.getLogger("mineagent")
if not _LOG.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOG.addHandler(handler)
    _LOG.setLevel(os.environ.get("MINEAGENT_LOG_LEVEL", "info").upper())


def log_event(event: str, fields: dict | None = None) -> None:
    payload = {"ts": time.time(), "event": event, **(fields or {})}
    if os.environ.get("MINEAGENT_JSON_LOGS", "1") == "1":
        _LOG.info(json.dumps(payload, ensure_ascii=False, default=str))
    else:
        _LOG.info("%s %s", event, fields or {})


class Metrics:
    def __init__(self) -> None:
        self.counters: dict = defaultdict(int)
        self.histograms: dict = defaultdict(list)

    def inc(self, name: str, value: int = 1) -> None:
        self.counters[name] += value

    def observe(self, name: str, value: float) -> None:
        bucket = self.histograms[name]
        bucket.append(float(value))
        if len(bucket) > 1000:
            del bucket[: len(bucket) - 1000]

    def snapshot(self) -> dict:
        out = {"counters": dict(self.counters), "histograms": {}}
        for name, values in self.histograms.items():
            if not values:
                out["histograms"][name] = {"count": 0, "avg": 0, "p95": 0}
                continue
            ordered = sorted(values)
            out["histograms"][name] = {
                "count": len(ordered),
                "avg": round(sum(ordered) / len(ordered), 2),
                "p95": round(ordered[int(len(ordered) * 0.95)], 2),
            }
        return out


metrics = Metrics()
'''


def render_checkpoint() -> str:
    return '''"""会话持久化：按 settings.session_store 选择 checkpointer。"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def get_checkpointer():
    store = (os.environ.get("MINEAGENT_SESSION_STORE") or "sqlite").lower()
    if store == "none":
        return None
    if store == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = Path(__file__).resolve().parent / ".sessions.db"
            conn = sqlite3.connect(str(path), check_same_thread=False)
            return SqliteSaver(conn)
        except Exception:  # noqa: BLE001
            return None
    if store == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            import psycopg

            conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
            saver = PostgresSaver(conn)
            saver.setup()
            return saver
        except Exception:  # noqa: BLE001
            return None
    return None
'''


def render_server(spec: Dict[str, Any]) -> str:
    name = spec.get("name") or "agent"
    return f'''""" {name} · 服务入口（由 MineAgent 生成）

运行：
    uvicorn server:app --host 0.0.0.0 --port 8000

接口：
    POST /chat          同步返回
    POST /chat/stream   SSE 流式
    GET  /health        存活
    GET  /ready         就绪
    GET  /metrics       指标
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import agent as flow
from settings import settings
from telemetry import log_event, metrics

try:
    from checkpoint import get_checkpointer
except Exception:  # noqa: BLE001
    def get_checkpointer():
        return None


app = FastAPI(title=settings.project_name, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors.split(",") if o.strip()] or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_graph = None


def graph():
    global _graph
    if _graph is None:
        try:
            _graph = flow.build_graph(get_checkpointer())
        except Exception:  # noqa: BLE001
            _graph = flow.build_graph()
    return _graph


class ChatRequest(BaseModel):
    message: str
    thread_id: str = ""


class ChatResponse(BaseModel):
    answer: str
    thread_id: str = ""
    usage: Dict[str, Any] = {{}}


def _check_auth(authorization: Optional[str]) -> None:
    if settings.auth == "none":
        return
    token = (authorization or "").replace("Bearer ", "").strip()
    if not token or token != settings.api_key:
        raise HTTPException(401, "unauthorized")


@app.get("/health")
def health():
    return {{"ok": True}}


@app.get("/ready")
def ready():
    ok = bool(os.environ.get("MINEAGENT_API_KEY") or os.environ.get("MINEAGENT_BASE_URL"))
    return JSONResponse({{"ok": ok}}, status_code=200 if ok else 503)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, authorization: Optional[str] = Header(default=None)):
    _check_auth(authorization)
    started = time.time()
    try:
        config = {{"configurable": {{"thread_id": req.thread_id}}}} if req.thread_id else {{}}
        result = graph().invoke(
            {{"data": req.message, "user_input": req.message, "route": ""}},
            config=config,
        )
        answer = result.get("data", "") if isinstance(result, dict) else ""
    except Exception as exc:  # noqa: BLE001
        metrics.inc("chat_errors")
        log_event("chat_error", {{"thread_id": req.thread_id, "error": str(exc)}})
        raise HTTPException(500, {{"error": str(exc), "thread_id": req.thread_id}}) from exc
    metrics.inc("chat_ok")
    metrics.observe("chat_latency_ms", (time.time() - started) * 1000)
    log_event("chat_ok", {{"thread_id": req.thread_id,
                           "latency_ms": round((time.time() - started) * 1000, 2)}})
    return ChatResponse(answer=answer, thread_id=req.thread_id)


@app.post("/chat/stream")
def chat_stream(req: ChatRequest, authorization: Optional[str] = Header(default=None)):
    _check_auth(authorization)

    def gen():
        started = time.time()
        yield "event: open\\ndata: {{}}\\n\\n"
        try:
            config = {{"configurable": {{"thread_id": req.thread_id}}}} if req.thread_id else {{}}
            for chunk in graph().stream(
                {{"data": req.message, "user_input": req.message, "route": ""}},
                config=config,
                stream_mode="updates",
            ):
                node = list(chunk.keys())[0] if isinstance(chunk, dict) and chunk else ""
                payload = json.dumps({{"node": node, "update": chunk}},
                                     ensure_ascii=False, default=str)
                yield f"event: update\\ndata: {{payload}}\\n\\n"
            yield "event: done\\ndata: {{}}\\n\\n"
            metrics.inc("stream_ok")
        except Exception as exc:  # noqa: BLE001
            payload = json.dumps({{"error": str(exc)}}, ensure_ascii=False)
            yield f"event: error\\ndata: {{payload}}\\n\\n"
            metrics.inc("stream_errors")
        finally:
            metrics.observe("stream_latency_ms", (time.time() - started) * 1000)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/metrics")
def prometheus():
    return JSONResponse(metrics.snapshot())
'''


def render_dockerfile() -> str:
    return '''FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
'''


def render_compose(slug: str) -> str:
    return f'''services:
  {slug or "agent"}:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./outputs:/app/outputs
      - ./skills:/app/skills
'''


def render_ci() -> str:
    return '''name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: python -m compileall -q .
      - run: python -m pytest -q
'''


def render_tests() -> str:
    return '''"""最小冒烟测试：服务能起、健康检查能过。不需要真实模型。"""
from __future__ import annotations

import os

os.environ.setdefault("MINEAGENT_API_KEY", "test-key")
os.environ.setdefault("MINEAGENT_BASE_URL", "http://127.0.0.1:9/v1")
os.environ.setdefault("MINEAGENT_SESSION_STORE", "none")


def test_server_imports():
    import server

    assert server.app is not None


def test_health():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    assert client.get("/health").json()["ok"] is True
'''


def render_requirements_extra() -> str:
    return "fastapi>=0.110\nuvicorn[standard]>=0.29\npydantic>=2.5\nhttpx>=0.27\npytest>=8.0\n"


def render_production_files(spec: Dict[str, Any], graph: Dict[str, Any],
                            framework: str) -> Dict[str, str]:
    """返回需要写进项目的生产化文件。"""
    if framework not in ("langchain", "autogen", "crewai"):
        return {}
    svc = merge_service(graph.get("service"))
    files: Dict[str, str] = {
        "settings.py": render_settings(spec, svc),
        "telemetry.py": render_telemetry(),
        "checkpoint.py": render_checkpoint(),
        "Dockerfile": render_dockerfile(),
        "docker-compose.yml": render_compose(spec.get("slug") or ""),
        ".github/workflows/ci.yml": render_ci(),
        "tests/test_smoke.py": render_tests(),
    }
    if framework == "langchain":
        files["server.py"] = render_server(spec)
    return files
