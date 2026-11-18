"""把画布级「服务设置」编译成项目里的生产化文件。

生成物（只对可运行的框架）：
- server.py     FastAPI 服务入口：/chat、/chat/stream、/health、/ready、/metrics
- settings.py   全部配置走环境变量
- telemetry.py  结构化日志 + 轻量 metrics
- checkpoint.py 会话持久化（SQLite / Postgres）
- Dockerfile / docker-compose.yml / .github/workflows/ci.yml / tests/
"""
from __future__ import annotations

import importlib.metadata
import json
import re
from typing import Any, Dict, List, Tuple

from .native import _LANGGRAPH_FRAMEWORKS

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "entry": {"mode": "both", "path": "/chat", "auth": "none", "cors": "*"},
    "session": {"store": "sqlite", "max_turns": 20, "ttl_minutes": 1440},
    "runtime": {"max_concurrency": 4, "queue_limit": 100, "run_timeout_s": 600, "resume": False},
    "observability": {"log_level": "info", "json_logs": True, "metrics": True,
                      "trace_sample": 1, "budget_usd": 0},
    "security": {"sandbox": "restricted", "guardrail": "log", "pii": False, "audit": True},
    # 外部数据中台：只配连接与逻辑数据集映射，不做数据集管理
    "data": {"enabled": False, "kind": "http", "base_url": "", "auth": "bearer",
             "secret_ref": "MINEAGENT_DATA_TOKEN", "datasets": [], "timeout_s": 30,
             "pii_fields": []},
    # 外部评测中台：只配连接与评测集映射，不做评测集管理
    "eval": {"enabled": False, "kind": "http", "base_url": "", "auth": "bearer",
             "secret_ref": "MINEAGENT_EVAL_TOKEN", "project": "", "evalsets": [],
             "report_on_run": True, "pass_rate": 0.8, "latency_p95_ms": 8000},
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
    d, ev = svc["data"], svc["eval"]
    return f'''"""服务配置：环境变量驱动，启动即校验，配错直接起不来。

改配置两种方式（优先级从高到低）：
    1. 直接设环境变量
    2. 写进同目录的 .env

看一眼当前生效的配置（密钥打码）：
    python settings.py
"""
from __future__ import annotations

import json
from typing import ClassVar, Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MINEAGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    project_name: str = {json.dumps(spec.get("name") or "agent", ensure_ascii=False)}

    entry_mode: Literal["http", "sse", "both"] = {_py(e["mode"])}
    entry_path: str = {_py(e["path"])}
    auth: Literal["none", "apikey", "oidc"] = {_py(e["auth"])}
    # 服务鉴权的 key，特意和模型 key（MINEAGENT_API_KEY）分开
    api_key: str = Field("", validation_alias="MINEAGENT_SERVICE_KEY")
    cors: str = {_py(e["cors"])}

    session_store: Literal["none", "sqlite", "postgres"] = {_py(s["store"])}
    max_turns: int = Field({int(s["max_turns"])}, ge=1, le=1000)
    session_ttl: int = Field({int(s["ttl_minutes"])}, ge=1, le=525600)

    max_concurrency: int = Field({int(r["max_concurrency"])}, ge=1, le=1024)
    queue_limit: int = Field({int(r["queue_limit"])}, ge=0, le=100000)
    run_timeout_s: int = Field({int(r["run_timeout_s"])}, ge=5, le=86400,
                               validation_alias="MINEAGENT_RUN_TIMEOUT")
    resume: bool = {_py(r["resume"])}

    log_level: str = {_py(o["log_level"])}
    json_logs: bool = {_py(o["json_logs"])}
    metrics_on: bool = Field({_py(o["metrics"])}, validation_alias="MINEAGENT_METRICS")
    trace_sample: float = Field({float(o["trace_sample"])}, ge=0.0, le=1.0)
    budget_usd: float = Field({float(o["budget_usd"])}, ge=0.0)
    # 成本核算：每 1K token 的单价（0 表示不折算；填上就会算 cost_usd 并按预算拦截）
    price_input_per_1k: float = Field(0.0, ge=0.0)
    price_output_per_1k: float = Field(0.0, ge=0.0)

    # 灰度：0=全走主版本，100=全走 canary；中间按 trace_id 稳定分流
    canary_percent: int = Field(0, ge=0, le=100)
    # 灰度这侧的版本标签（例如 1.1.0），只在 /version 与日志里展示，不影响运行
    canary_label: str = ""
    canary_version: str = ""

    sandbox: str = {_py(sec["sandbox"])}
    guardrail: str = {_py(sec["guardrail"])}
    pii: bool = {_py(sec["pii"])}
    audit: bool = {_py(sec["audit"])}
    # 输入护栏的长度上限（字符）；0 表示不限
    max_input_chars: int = Field(8000, ge=0, le=1000000)

    # 外部数据中台
    data_enabled: bool = {_py(d["enabled"])}
    data_kind: str = {_py(d["kind"])}
    data_base_url: str = {_py(d["base_url"])}
    data_auth: str = {_py(d["auth"])}
    data_timeout_s: int = Field({int(d["timeout_s"])}, ge=1, le=3600,
                                validation_alias="MINEAGENT_DATA_TIMEOUT")

    # 外部评测中台
    eval_enabled: bool = {_py(ev["enabled"])}
    eval_kind: str = {_py(ev["kind"])}
    eval_base_url: str = {_py(ev["base_url"])}
    eval_project: str = {_py(ev["project"])}
    eval_pass_rate: float = Field({float(ev["pass_rate"])}, ge=0.0, le=1.0)

    # 已从画布编译进来、但服务端还没实现对应行为的配置项（启动会打一条 warn）
    UNIMPLEMENTED: ClassVar[tuple] = ()

    @field_validator("entry_path")
    @classmethod
    def _entry_path_must_start_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("必须以 / 开头，例如 /chat")
        return value

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return (value or "info").strip().lower()


def load_settings() -> Settings:
    """校验不过就退出：宁可起不来，也不要带着错配置对外服务。"""
    try:
        return Settings()
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            where = ".".join(str(part) for part in err["loc"]) or "(root)"
            lines.append(f"  - {{where}}: {{err['msg']}}")
        raise SystemExit(
            "服务配置校验失败，进程不会启动：\\n"
            + "\\n".join(lines)
            + "\\n请对照 .env.example 修好后再启动。"
        ) from None


settings = load_settings()

# 服务鉴权 key 允许放在 Vault / 受控文件里（环境变量仍然是最高优先级）
try:
    from secret_store import get_secret as _get_secret

    if not settings.api_key:
        settings.api_key = _get_secret("MINEAGENT_SERVICE_KEY", "")
except Exception:  # noqa: BLE001
    pass


if __name__ == "__main__":
    data = settings.model_dump()
    if data.get("api_key"):
        data["api_key"] = data["api_key"][:4] + "****"
    print(json.dumps(data, ensure_ascii=False, indent=2))
'''


def render_telemetry() -> str:
    return '''"""结构化日志 + 轻量 metrics（零依赖，够用就好）。"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from collections import defaultdict
from pathlib import Path


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
        self.floats: dict = defaultdict(float)

    def inc(self, name: str, value: int = 1) -> None:
        self.counters[name] += value

    def add(self, name: str, value: float) -> None:
        """浮点累加（成本这类不能取整的指标用这个）。"""
        self.floats[name] += float(value)

    def observe(self, name: str, value: float) -> None:
        bucket = self.histograms[name]
        bucket.append(float(value))
        if len(bucket) > 1000:
            del bucket[: len(bucket) - 1000]

    def snapshot(self) -> dict:
        out = {"counters": dict(self.counters), "floats": dict(self.floats), "histograms": {}}
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

    def render_prometheus(self) -> str:
        """Prometheus 文本格式（/metrics 默认吐这个，不是 JSON）。"""
        lines: list = []
        for name, value in sorted(self.counters.items()):
            metric = "mineagent_" + name.replace(".", "_")
            lines.append(f"# TYPE {metric}_total counter")
            lines.append(f"{metric}_total {value}")
        for name, value in sorted(self.floats.items()):
            metric = "mineagent_" + name.replace(".", "_")
            lines.append(f"# TYPE {metric}_total counter")
            lines.append(f"{metric}_total {round(value, 6)}")
        for name, values in sorted(self.histograms.items()):
            metric = "mineagent_" + name.replace(".", "_")
            ordered = sorted(values)
            lines.append(f"# TYPE {metric} summary")
            if ordered:
                count = len(ordered)
                lines.append(f"{metric}_count {count}")
                lines.append(f"{metric}_sum {round(sum(ordered), 3)}")
                for q in (0.5, 0.95, 0.99):
                    idx = min(count - 1, int(count * q))
                    lines.append(f'{metric}{{quantile="{q}"}} {round(ordered[idx], 3)}')
            else:
                lines.append(f"{metric}_count 0")
        return "\\n".join(lines) + "\\n"


metrics = Metrics()


# ── 可观测：OTel 导出（可选）+ trace 落盘（可选）──────────────────────
_OBS: dict = {"otel": False, "endpoint": "", "trace_file": "", "service": "agent"}
_TRACER = None


def init_observability(service_name: str = "agent", sample_rate: float = 1.0) -> dict:
    """按环境变量决定要不要导出 OTel / 落 trace 文件；没配就什么都不做。"""
    global _TRACER
    _OBS["service"] = service_name
    _OBS["sample_rate"] = max(0.0, min(1.0, float(sample_rate or 0.0)))
    endpoint = (os.environ.get("MINEAGENT_OTEL_ENDPOINT") or "").strip()
    trace_file = (os.environ.get("MINEAGENT_TRACE_FILE") or "").strip()
    _OBS["endpoint"] = endpoint
    _OBS["trace_file"] = trace_file

    if endpoint:
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

            provider = TracerProvider(
                resource=Resource.create({"service.name": service_name}),
                sampler=ParentBased(TraceIdRatioBased(_OBS["sample_rate"])),
            )
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            trace.set_tracer_provider(provider)
            _TRACER = trace.get_tracer(service_name)
            _OBS["otel"] = True
        except Exception as exc:  # noqa: BLE001
            # 配了地址却装不上 SDK：吵一句，别让人以为已经在导出
            _LOG.warning("OTel 未启用：%s（pip install opentelemetry-sdk "
                         "opentelemetry-exporter-otlp-proto-http）", exc)

    log_event("observability", {"service": service_name, "otel": _OBS["otel"],
                                "otel_endpoint": endpoint, "trace_file": trace_file,
                                "sample_rate": _OBS["sample_rate"]})
    return dict(_OBS)


def span(name: str, attributes: dict | None = None):
    """拿一个 span 上下文；没配 OTel 时是空操作，调用处不用分叉。"""
    if _TRACER is None:
        return contextlib.nullcontext()
    return _TRACER.start_as_current_span(name, attributes=attributes or {})


def trace_event(event: str, fields: dict | None = None, sampled: bool = True) -> None:
    """把一条事件追加到 trace 文件（JSONL；文件名里可以写 {date} 按天切）。"""
    path = _OBS.get("trace_file") or ""
    if not path or not sampled:
        return
    try:
        target = Path(str(path).replace("{date}", time.strftime("%Y-%m-%d")))
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "event": event, **(fields or {})},
                                ensure_ascii=False, default=str) + "\\n")
    except Exception:  # noqa: BLE001
        pass
'''


def render_checkpoint() -> str:
    return '''"""会话持久化：按 settings.session_store 选择 checkpointer。

人工审批（interrupt / resume）必须有 checkpointer 才能挂起和恢复：
- none     → 内存态（进程内可续跑，重启即丢）
- sqlite   → 落 .sessions.db（默认，单机可重启续跑）
- postgres → 落 Postgres（多副本部署用）
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

try:
    from secret_store import get_secret as _secret
except Exception:  # noqa: BLE001
    def _secret(name: str, default: str = "") -> str:
        return os.environ.get(name, default)


def get_checkpointer():
    store = (os.environ.get("MINEAGENT_SESSION_STORE") or "sqlite").lower()

    if store == "none":
        # 内存态也必须有 checkpointer：否则 interrupt 挂不住、resume 无处可取
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()

    if store == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            # 不要静默退化成内存态：那会让「重启续跑 / 人工审批」悄悄失效
            raise SystemExit(
                "会话存储选了 sqlite，但缺少 langgraph-checkpoint-sqlite。"
                "请执行：pip install langgraph-checkpoint-sqlite"
            ) from exc
        path = Path(__file__).resolve().parent / ".sessions.db"
        conn = sqlite3.connect(str(path), check_same_thread=False)
        saver = SqliteSaver(conn)
        if hasattr(saver, "setup"):
            saver.setup()
        return saver

    if store == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            import psycopg

            conn = psycopg.connect(_secret("DATABASE_URL"), autocommit=True)
            saver = PostgresSaver(conn)
            saver.setup()
            return saver
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                "会话存储选了 postgres，但连不上或缺少依赖（langgraph-checkpoint-postgres / psycopg）。"
                f"原因：{exc}"
            ) from exc

    # 未知取值：退回内存态，但要让调用方看见
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()
'''


def render_data_client() -> str:
    return '''"""数据中台客户端（由 MineAgent 生成）。

配置来自项目根目录的 integrations.json，token 从环境变量读（secret_ref）。
默认只读；写入需要把对应数据集配置成 mode=write。
"""
from __future__ import annotations

import importlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF: dict = {}
try:
    CONF = json.loads((HERE.parent / "integrations.json").read_text(encoding="utf-8")).get("data", {})
except Exception:  # noqa: BLE001
    CONF = {}


def _token() -> str:
    name = CONF.get("secret_ref") or "MINEAGENT_DATA_TOKEN"
    try:
        from secret_store import get_secret
        return get_secret(name, "")
    except Exception:  # noqa: BLE001
        return os.environ.get(name, "")


def _headers() -> dict:
    headers = {"Accept": "application/json"}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _dataset_spec(logical: str) -> dict:
    for item in CONF.get("datasets") or []:
        if isinstance(item, dict) and item.get("logical") == logical:
            return item
    raise ValueError(f"未配置的数据集：{logical}")


def _http_json(url: str):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=int(CONF.get("timeout_s") or 30)) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def read_dataset(logical: str, filters: dict | None = None, limit: int = 100) -> list:
    """按逻辑数据集名取数：画布只认逻辑名，物理表在 integrations.json 里映射。"""
    if not CONF.get("enabled"):
        raise RuntimeError("数据中台未启用（integrations.json → data.enabled）")
    spec = _dataset_spec(logical)
    kind = (CONF.get("kind") or "http").lower()
    if kind == "http":
        params = {"limit": int(limit)}
        if filters:
            params["filters"] = json.dumps(filters, ensure_ascii=False)
        name = spec.get("physical") or logical
        base = (CONF.get("base_url") or "").rstrip("/")
        url = base + f"/datasets/{urllib.parse.quote(str(name), safe='')}/rows?" + urllib.parse.urlencode(params)
        payload = _http_json(url)
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        return rows or []
    if kind == "sdk":
        module = importlib.import_module(CONF.get("module") or "data_sdk")
        return list(module.read_dataset(logical, filters=filters, limit=limit))
    raise RuntimeError(f"kind={kind} 需要额外依赖，请改 integrations/data_client.py")


def write_records(logical: str, rows: list) -> int:
    """写回数据中台：默认拒绝，只有 mode=write 的数据集才允许。"""
    spec = _dataset_spec(logical)
    if spec.get("mode") != "write":
        raise PermissionError(f"数据集 {logical} 未配置为可写（mode=write）")
    if (CONF.get("kind") or "http").lower() != "http":
        raise RuntimeError("只有 http 适配支持写入，其他类型请自行扩展")
    name = spec.get("physical") or logical
    base = (CONF.get("base_url") or "").rstrip("/")
    url = base + f"/datasets/{urllib.parse.quote(str(name), safe='')}/rows"
    body = json.dumps({"rows": rows}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={**_headers(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=int(CONF.get("timeout_s") or 30)) as resp:
        payload = json.loads(resp.read().decode("utf-8") or "{}")
    return int(payload.get("written") or len(rows))


def check() -> bool:
    """探活用：未启用直接视为通过。"""
    if not CONF.get("enabled"):
        return True
    base = (CONF.get("base_url") or "").rstrip("/")
    if not base:
        return False
    try:
        _http_json(base + "/health")
        return True
    except Exception:  # noqa: BLE001
        return False
'''


def render_eval_client() -> str:
    return '''"""评测中台客户端（由 MineAgent 生成）。

- fetch_cases(evalset)  拉评测集
- report(...)           上报单条结果
- check()               探活

配置来自 integrations.json 的 eval 段，token 从环境变量读。
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF: dict = {}
try:
    CONF = json.loads((HERE.parent / "integrations.json").read_text(encoding="utf-8")).get("eval", {})
except Exception:  # noqa: BLE001
    CONF = {}


def _token() -> str:
    name = CONF.get("secret_ref") or "MINEAGENT_EVAL_TOKEN"
    try:
        from secret_store import get_secret
        return get_secret(name, "")
    except Exception:  # noqa: BLE001
        return os.environ.get(name, "")


def _headers() -> dict:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _remote_evalset(logical: str) -> str:
    for item in CONF.get("evalsets") or []:
        if isinstance(item, dict) and item.get("logical") == logical:
            return str(item.get("remote") or logical)
    return logical


def fetch_cases(evalset: str, limit: int = 0) -> list:
    if not CONF.get("enabled"):
        raise RuntimeError("评测中台未启用（integrations.json → eval.enabled）")
    name = urllib.parse.quote(_remote_evalset(evalset), safe="")
    url = (CONF.get("base_url") or "").rstrip("/") + f"/evalsets/{name}/cases"
    if limit:
        url += f"?limit={int(limit)}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8") or "{}")
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    return cases or []


def report(evalset: str, case_id: str, answer: str, scores: dict,
           usage: dict | None = None) -> None:
    if not CONF.get("enabled"):
        return
    base = (CONF.get("base_url") or "").rstrip("/")
    body = {
        "project": CONF.get("project") or "",
        "evalset": _remote_evalset(evalset),
        "case_id": case_id,
        "answer": answer,
        "scores": scores or {},
        "usage": usage or {},
    }
    req = urllib.request.Request(
        base + "/eval-runs",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=_headers(),
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def check() -> bool:
    if not CONF.get("enabled"):
        return True
    base = (CONF.get("base_url") or "").rstrip("/")
    if not base:
        return False
    try:
        req = urllib.request.Request(base + "/health", headers=_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except Exception:  # noqa: BLE001
        return False
'''


def render_eval_run(spec: Dict[str, Any]) -> str:
    name = json.dumps(spec.get("name") or "agent", ensure_ascii=False)
    return f'''"""批量评测：拉评测集 → 调 agent → 规则打分 → 上报评测中台。

用法：
    python -m integrations.eval_run --set smoke --limit 20
"""
from __future__ import annotations

import argparse
import json
import time

from integrations import eval_client

PROJECT = {name}


def _score(expected: str, answer: str) -> dict:
    expected = (expected or "").strip()
    answer = (answer or "").strip()
    if not expected:
        return {{"match": 0.0}}
    return {{"match": 1.0 if expected in answer else 0.0}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", dest="evalset", default="smoke")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    import agent

    cases = eval_client.fetch_cases(args.evalset, limit=args.limit)
    passed = 0
    latencies = []
    for case in cases:
        started = time.time()
        answer = agent.main(str(case.get("input") or ""))
        latency = (time.time() - started) * 1000
        latencies.append(latency)
        scores = _score(str(case.get("expected") or ""), answer)
        if scores.get("match", 0) >= 0.5:
            passed += 1
        try:
            eval_client.report(args.evalset, str(case.get("id") or ""), answer, scores,
                               {{"latency_ms": round(latency, 1)}})
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 上报失败：{{exc}}")

    total = len(cases) or 1
    pass_rate = passed / total
    p95 = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0
    summary = {{"project": PROJECT, "evalset": args.evalset, "cases": len(cases),
               "pass_rate": round(pass_rate, 4), "p95_latency_ms": round(p95, 1)}}
    print(json.dumps(summary, ensure_ascii=False))
    threshold = float((eval_client.CONF or {{}}).get("pass_rate") or 0.8)
    return 0 if pass_rate >= threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def render_integrations_json(svc: Dict[str, Dict[str, Any]]) -> str:
    return json.dumps({"data": svc["data"], "eval": svc["eval"]},
                      ensure_ascii=False, indent=2) + "\n"


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

import contextvars
import hashlib
import json
import os
import random
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

import agent as flow
from settings import settings
from telemetry import init_observability, log_event, metrics, span, trace_event

try:
    import secret_store as _secrets
except Exception:  # noqa: BLE001
    _secrets = None

try:
    import security as _security
except Exception:  # noqa: BLE001
    _security = None

try:
    from checkpoint import get_checkpointer
except Exception:  # noqa: BLE001
    def get_checkpointer():
        return None

try:
    import sandbox as _sandbox
except Exception:  # noqa: BLE001
    _sandbox = None


def _check_sandbox() -> None:
    """导入时就把沙箱配置校验掉：选了声称隔离的模式，就必须真的能隔离。"""
    if _sandbox is None:
        return
    info = _sandbox.describe()
    log_event("sandbox", info)
    if info["mode"] == "container" and not info["docker"]:
        raise SystemExit("执行沙箱配成 container，但本机没有 docker；"
                         "装好 docker 或把 MINEAGENT_SANDBOX 改成 restricted。")


_check_sandbox()
# 观测在导入时就初始化：uvicorn 与测试客户端都会走到，不依赖 startup 事件
OBSERVABILITY = init_observability(settings.project_name, settings.trace_sample)


app = FastAPI(title=settings.project_name, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors.split(",") if o.strip()] or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)


@app.middleware("http")
async def _trace_middleware(request: Request, call_next):
    """每个请求一个 trace id：参数校验失败、500 也照样带回，方便对日志。"""
    trace_id = _new_trace_id(request.headers.get("X-Trace-Id"))
    request.state.trace_id = trace_id
    with span(f"{{request.method}} {{request.url.path}}", {{"trace_id": trace_id}}):
        response = await call_next(request)
    response.headers.setdefault("X-Trace-Id", trace_id)
    variant = getattr(request.state, "variant", "")
    if variant:
        response.headers.setdefault("X-Variant", variant)
    return response

# ── 并发闸门：同时执行的数量受 max_concurrency 限制，排队的受 queue_limit 限制 ──
_slots = threading.BoundedSemaphore(max(1, settings.max_concurrency))
_queue_lock = threading.Lock()
_queue_waiting = 0


def _acquire_slot(wait_s: float) -> None:
    """拿一个执行位；排队超限直接 429，不无限堆积请求。"""
    global _queue_waiting
    with _queue_lock:
        if _queue_waiting >= max(0, settings.queue_limit):
            raise HTTPException(429, "queue is full")
        _queue_waiting += 1
    try:
        if not _slots.acquire(timeout=max(1.0, wait_s)):
            raise HTTPException(429, "server is busy")
    finally:
        with _queue_lock:
            _queue_waiting -= 1


def _release_slot() -> None:
    try:
        _slots.release()
    except ValueError:
        pass


def _new_trace_id(incoming: Optional[str]) -> str:
    """沿用调用方传的 trace id（网关 / 前端可以串起来），没有就现生成一个。"""
    return (incoming or "").strip()[:64] or uuid.uuid4().hex[:16]


def _bind_trace(trace_id: str) -> None:
    """把 trace id 绑到本次执行上下文，节点事件会自动带上它。"""
    setter = getattr(flow, "set_trace_id", None)
    if callable(setter):
        setter(trace_id)


def _drop_thread(thread_id: str) -> None:
    """用完即弃的会话：没传 thread_id 的请求跑完就把 checkpoint 删掉，别让库一直长。"""
    saver = getattr(graph(), "checkpointer", None)
    drop = getattr(saver, "delete_thread", None)
    if callable(drop):
        try:
            drop(thread_id)
        except Exception:  # noqa: BLE001
            pass


def _invoke_with_deadline(fn, timeout_s: float):
    """整条 run 的墙钟上限：超时返回 504，而不是挂到客户端自己断。"""
    pool = ThreadPoolExecutor(max_workers=1)
    # 复制上下文：agent 里的 token 用量记在 ContextVar 上，不复制就取不回来
    ctx = contextvars.copy_context()
    future = pool.submit(ctx.run, fn)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout:
        future.cancel()
        raise HTTPException(504, f"run exceeded {{timeout_s}}s") from None
    finally:
        pool.shutdown(wait=False)


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
    status: str = "ok"          # ok | interrupted
    interrupt: Optional[Dict[str, Any]] = None
    variant: str = "primary"    # primary | canary


def _pick_variant(request, trace_id: str) -> str:
    """灰度分流：显式 header 优先，其次按百分比（用 trace_id 做稳定哈希，同一个请求不会摇摆）。"""
    forced = (request.headers.get("X-Canary") or "").strip().lower()
    if forced in ("1", "true", "yes", "on"):
        return "canary"
    if forced in ("0", "false", "no", "off"):
        return "primary"
    percent = int(getattr(settings, "canary_percent", 0) or 0)
    if percent <= 0:
        return "primary"
    if percent >= 100:
        return "canary"
    bucket = int(hashlib.md5(trace_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    variant = "canary" if bucket < percent else "primary"
    # 没配 canary 模型时不要谎报：流量仍然走主模型
    if variant == "canary" and getattr(flow, "llm_canary", None) is None:
        return "primary"
    return variant


class ResumeRequest(BaseModel):
    thread_id: str
    decision: str = "approve"
    comment: str = ""


# ── 成本核算与预算 ──────────────────────────────────────────────
_SPENT = {{"usd": 0.0}}


def _cost_usd(usage: dict) -> float:
    """按每 1K token 单价折算本次成本；没配单价就是 0。"""
    price_in = float(getattr(settings, "price_input_per_1k", 0.0) or 0.0)
    price_out = float(getattr(settings, "price_output_per_1k", 0.0) or 0.0)
    if not price_in and not price_out:
        return 0.0
    prompt = float(usage.get("prompt_tokens") or 0)
    completion = float(usage.get("completion_tokens") or 0)
    return round(prompt / 1000 * price_in + completion / 1000 * price_out, 6)


def _account(usage: dict) -> dict:
    """把成本写进 usage，并累加到进程内计数（/metrics 会吐 mineagent_cost_usd_total）。"""
    cost = _cost_usd(usage)
    usage = dict(usage or {{}})
    usage["cost_usd"] = cost
    if cost:
        _SPENT["usd"] += cost
        metrics.add("cost_usd", cost)
    usage["spent_usd"] = round(_SPENT["usd"], 6)
    return usage


def _budget_left() -> float | None:
    """还剩多少预算；没设预算返回 None。"""
    budget = float(getattr(settings, "budget_usd", 0.0) or 0.0)
    if budget <= 0:
        return None
    return round(budget - _SPENT["usd"], 6)


def _ensure_budget() -> None:
    left = _budget_left()
    if left is not None and left <= 0:
        metrics.inc("budget_exhausted")
        raise HTTPException(429, "预算已用尽（MINEAGENT_BUDGET_USD），请调高预算或重置进程")


def _record_candidate(message: str, error: str, trace_id: str, thread_id: str) -> None:
    """出错的请求收进 evals/candidates.jsonl，攒够了人工改成正式用例（评测飞轮）。"""
    try:
        text = message or ""
        if _security is not None and getattr(settings, "pii", False):
            text = _security.redact(text)[0]
        path = Path(__file__).resolve().parent / "evals" / "candidates.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({{"input": text, "error": str(error)[:500],
                                 "trace_id": trace_id, "thread_id": thread_id,
                                 "ts": time.time()}}, ensure_ascii=False) + "\\n")
        metrics.inc("eval_candidates")
    except Exception:  # noqa: BLE001
        pass


# ── 会话治理：轮数上限 + 过期清理（只对调用方指定了 thread_id 的会话生效）──
_META_DB = Path(__file__).resolve().parent / ".sessions-meta.db"


def _session_begin(thread_id: str) -> Dict[str, Any]:
    """记一轮并检查上限/过期：超了就清掉 checkpointer 里的状态，从头开始。"""
    ttl_minutes = int(getattr(settings, "session_ttl", 0) or 0)
    max_turns = int(getattr(settings, "max_turns", 0) or 0)
    info: Dict[str, Any] = {{"turns": 1, "expired": False, "reset": False}}
    if not ttl_minutes and not max_turns:
        return info
    now = time.time()
    try:
        conn = sqlite3.connect(str(_META_DB), timeout=5)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS sessions("
                         "thread_id TEXT PRIMARY KEY, turns INTEGER, updated_at REAL)")
            row = conn.execute("SELECT turns, updated_at FROM sessions WHERE thread_id=?",
                               (thread_id,)).fetchone()
            turns = int(row[0]) if row else 0
            last = float(row[1]) if row else 0.0
            expired = bool(row and ttl_minutes and (now - last) > ttl_minutes * 60)
            too_many = bool(max_turns and turns >= max_turns)
            if expired or too_many:
                _drop_thread(thread_id)
                info["expired"] = expired
                info["reset"] = True
                metrics.inc("session_reset")
                log_event("session_reset", {{"thread_id": thread_id,
                                             "expired": expired, "turns": turns}})
                turns = 0
            turns += 1
            conn.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?)",
                         (thread_id, turns, now))
            conn.commit()
            info["turns"] = turns
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass
    return info


def _sampled() -> bool:
    """trace_sample 采样：0 不记、1 全记、中间按比例。"""
    rate = float(getattr(settings, "trace_sample", 1.0) or 0.0)
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    return random.random() < rate


def _audit(event: str, request, **fields) -> None:
    """审计：只记身份指纹与结果，不记原始 token，也不记用户正文。"""
    if _security is None:
        return
    client = getattr(request, "client", None)
    payload = {{"ip": getattr(client, "host", ""),
                "ua": (request.headers.get("User-Agent") or "")[:120],
                "auth": _security.fingerprint(request.headers.get("Authorization") or "")}}
    payload.update(fields)
    _security.audit(event, payload, enabled=bool(settings.audit))


def _guard_input(text: str, trace_id: str, request=None) -> None:
    """输入护栏：block 直接 400，log 只记一笔；被拦下的请求同样进审计。"""
    if _security is None:
        return
    issues = _security.check_input(text, int(getattr(settings, "max_input_chars", 8000) or 0))
    if not issues:
        return
    metrics.inc("guardrail_hits")
    mode = (getattr(settings, "guardrail", "log") or "log").lower()
    log_event("guardrail_warn", {{"trace_id": trace_id, "mode": mode, "issues": issues}})
    if request is not None:
        _audit("chat_blocked" if mode == "block" else "chat_guarded", request,
               trace_id=trace_id, issues=issues)
    if mode == "block":
        raise HTTPException(400, {{"error": "输入未通过安全检查", "issues": issues,
                                   "trace_id": trace_id}})


def _interrupt_items(result) -> list:
    """把 LangGraph 的 __interrupt__ 归一成普通 dict 列表。"""
    if isinstance(result, dict):
        items = result.get("__interrupt__")
    else:
        items = result
    out = []
    for item in items or []:
        value = getattr(item, "value", item)
        out.append(value if isinstance(value, dict) else {{"value": str(value)}})
    return out


def _check_auth(authorization: Optional[str]) -> None:
    if settings.auth == "none":
        return
    if settings.auth == "oidc":
        # OIDC 还没实现：宁可拒绝，也不要让人以为已经鉴过上
        raise HTTPException(501, "auth=oidc 尚未实现，请改用 apikey 或 none")
    token = (authorization or "").replace("Bearer ", "").strip()
    if not token or token != settings.api_key:
        raise HTTPException(401, "unauthorized")


@app.on_event("startup")
def _startup_report() -> None:
    log_event("service_start", {{"project": settings.project_name,
                                 "entry_mode": settings.entry_mode,
                                 "entry_path": settings.entry_path,
                                 "auth": settings.auth,
                                 "max_concurrency": settings.max_concurrency,
                                 "queue_limit": settings.queue_limit,
                                 "run_timeout_s": settings.run_timeout_s}})
    if settings.UNIMPLEMENTED:
        # 这些开关已经写进配置但运行时不生效，宁可吵一句也不要让交付方误会
        log_event("service_settings_unimplemented",
                  {{"keys": list(settings.UNIMPLEMENTED)}})
    if settings.canary_percent > 0 and getattr(flow, "llm_canary", None) is None:
        log_event("canary_not_configured",
                  {{"canary_percent": settings.canary_percent,
                    "hint": "配了灰度比例但没有 MINEAGENT_CANARY_MODEL / _BASE_URL，流量仍走主模型"}})
    if not bool(getattr(settings, "resume", False)):
        log_event("resume_disabled",
                  {{"hint": "断点续跑关闭：/resume 会返回 501；画布上有审批节点时请开启 MINEAGENT_RESUME=1"}})


@app.get("/health")
def health():
    return {{"ok": True, "version": getattr(flow, "AGENT_VERSION", "0.0.0")}}


@app.get("/version")
def version():
    """返回生成器写入的版本记录（版本号 / 内容 hash / 生成时间 / 节点数 + 灰度信息）。"""
    try:
        info = json.loads((Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        info = {{"version": getattr(flow, "AGENT_VERSION", "0.0.0")}}
    canary_model = getattr(flow, "llm_canary", None)
    info["variants"] = {{
        "primary": {{"version": info.get("version", ""), "model": getattr(flow.llm, "model_name", "")}},
        "canary": ({{
            "version": settings.canary_version or "",
            "label": settings.canary_label or "",
            "model": getattr(canary_model, "model_name", "") if canary_model else "",
            "percent": settings.canary_percent,
        }} if canary_model is not None else None),
    }}
    info["canary_percent"] = settings.canary_percent
    return info


@app.get("/ready")
def ready():
    missing = []
    if not (os.environ.get("MINEAGENT_API_KEY") or os.environ.get("MINEAGENT_BASE_URL")):
        missing.append("MINEAGENT_API_KEY 或 MINEAGENT_BASE_URL")
    payload = {{"ok": not missing, "missing": missing,
                "unimplemented": list(settings.UNIMPLEMENTED)}}
    if _sandbox is not None:
        payload["sandbox"] = _sandbox.describe()
    if _secrets is not None:
        payload["secrets"] = _secrets.status()
    payload["security"] = {{"guardrail": settings.guardrail, "pii": bool(settings.pii),
                            "audit": bool(settings.audit),
                            "max_input_chars": int(settings.max_input_chars)}}
    return JSONResponse(payload, status_code=200 if not missing else 503)


def chat(req: ChatRequest, request: Request,
         authorization: Optional[str] = Header(default=None)):
    _check_auth(authorization)
    trace_id = getattr(request.state, "trace_id", "") or _new_trace_id(None)
    # 有 checkpointer 就必须给 thread_id：没传就现造一个，跑完再删掉
    thread_id = req.thread_id or uuid.uuid4().hex[:16]
    _ensure_budget()
    _guard_input(req.message, trace_id, request)
    # 调用方显式给了 thread_id 才做轮数/过期治理；一次性请求不必记账
    session_turns = _session_begin(thread_id)["turns"] if req.thread_id else 1
    sampled = _sampled()
    variant = _pick_variant(request, trace_id)
    request.state.variant = variant
    started = time.time()
    _acquire_slot(settings.run_timeout_s)
    usage: Dict[str, Any] = {{}}
    interrupts: list = []
    try:
        flow.reset_usage()
        _bind_trace(trace_id)
        flow.set_canary(variant == "canary")
        config = {{"configurable": {{"thread_id": thread_id}}}}
        payload = {{"data": req.message, "user_input": req.message, "route": "",
                   "trace_id": trace_id}}
        result = _invoke_with_deadline(
            lambda: graph().invoke(payload, config=config), settings.run_timeout_s)
        answer = result.get("data", "") if isinstance(result, dict) else ""
        interrupts = _interrupt_items(result)
    except HTTPException:
        metrics.inc("chat_errors")
        raise
    except Exception as exc:  # noqa: BLE001
        metrics.inc("chat_errors")
        log_event("chat_error", {{"trace_id": trace_id, "thread_id": req.thread_id,
                                  "error": str(exc)}})
        _record_candidate(req.message, str(exc), trace_id, thread_id)
        raise HTTPException(500, {{"error": str(exc), "thread_id": req.thread_id,
                                   "trace_id": trace_id}}) from exc
    finally:
        usage = _account(flow.take_usage())
        if not req.thread_id and not interrupts:
            _drop_thread(thread_id)
        _release_slot()
    metrics.inc("chat_ok")
    metrics.inc("chat_canary" if variant == "canary" else "chat_primary")
    metrics.observe(f"chat_latency_{{variant}}", (time.time() - started) * 1000)
    # 输出侧脱敏：响应、日志、trace 都只留脱敏后的文本
    if _security is not None and bool(getattr(settings, "pii", False)) and answer:
        answer, pii_hits = _security.redact(answer)
        if pii_hits:
            metrics.inc("pii_redacted")
            log_event("pii_redacted", {{"trace_id": trace_id, "hits": pii_hits}})
    metrics.observe("chat_latency_ms", (time.time() - started) * 1000)
    log_event("chat_ok", {{"trace_id": trace_id, "thread_id": thread_id,
                           "variant": variant,
                           "latency_ms": round((time.time() - started) * 1000, 2),
                           "usage": usage, "interrupted": bool(interrupts)}})
    trace_event("chat_ok" if not interrupts else "chat_interrupted",
                {{"trace_id": trace_id, "thread_id": thread_id, "variant": variant,
                  "turns": session_turns,
                  "latency_ms": round((time.time() - started) * 1000, 2),
                  "usage": usage, "interrupt": interrupts[0] if interrupts else None}},
                sampled=sampled)
    _audit("chat_ok" if not interrupts else "chat_interrupted", request,
           trace_id=trace_id, thread_id=thread_id, variant=variant,
           tokens=usage.get("total_tokens", 0), cost_usd=usage.get("cost_usd", 0.0))
    if interrupts:
        return ChatResponse(answer="", thread_id=thread_id, usage=usage,
                            status="interrupted", interrupt=interrupts[0], variant=variant)
    return ChatResponse(answer=answer, thread_id=thread_id, usage=usage, variant=variant)


@app.post("/resume", response_model=ChatResponse)
def resume(req: ResumeRequest, request: Request,
           authorization: Optional[str] = Header(default=None)):
    """把挂起的人工审批放行：decision = approve / reject（也可以传别的原因）。"""
    if not bool(getattr(settings, "resume", False)):
        # 开关关掉时直接拒绝，别让人以为「点了 approve 但没生效」
        metrics.inc("resume_disabled")
        raise HTTPException(501, "此部署未开启断点续跑（MINEAGENT_RESUME=0），/resume 不可用")
    _check_auth(authorization)
    trace_id = getattr(request.state, "trace_id", "") or _new_trace_id(None)
    _ensure_budget()
    variant = _pick_variant(request, trace_id)
    request.state.variant = variant
    started = time.time()
    _acquire_slot(settings.run_timeout_s)
    usage: Dict[str, Any] = {{}}
    interrupts: list = []
    try:
        flow.reset_usage()
        _bind_trace(trace_id)
        flow.set_canary(variant == "canary")
        config = {{"configurable": {{"thread_id": req.thread_id}}}}
        # 没有待审批就别假装恢复了：明确 409，省得调用方以为已经放行
        try:
            snapshot = graph().get_state(config)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(404, {{"error": str(exc), "thread_id": req.thread_id}}) from exc
        if not _interrupt_items(getattr(snapshot, "interrupts", ())):
            metrics.inc("resume_no_pending")
            raise HTTPException(409, {{"error": "这条会话没有待审批的挂起状态",
                                       "thread_id": req.thread_id, "trace_id": trace_id}})
        result = _invoke_with_deadline(
            lambda: graph().invoke(Command(resume=req.decision), config=config),
            settings.run_timeout_s)
        answer = result.get("data", "") if isinstance(result, dict) else ""
        interrupts = _interrupt_items(result)
    except HTTPException:
        metrics.inc("resume_errors")
        raise
    except Exception as exc:  # noqa: BLE001
        metrics.inc("resume_errors")
        log_event("resume_error", {{"trace_id": trace_id, "thread_id": req.thread_id,
                                    "error": str(exc)}})
        raise HTTPException(500, {{"error": str(exc), "thread_id": req.thread_id,
                                   "trace_id": trace_id}}) from exc
    finally:
        usage = _account(flow.take_usage())
        _release_slot()
    metrics.inc("resume_ok")
    log_event("resume_ok", {{"trace_id": trace_id, "thread_id": req.thread_id,
                             "decision": req.decision,
                             "latency_ms": round((time.time() - started) * 1000, 2),
                             "usage": usage}})
    trace_event("resume_ok", {{"trace_id": trace_id, "thread_id": req.thread_id,
                              "variant": variant, "decision": req.decision, "usage": usage,
                              "status": "interrupted" if interrupts else "ok"}},
                sampled=_sampled())
    _audit("resume_ok", request, trace_id=trace_id, thread_id=req.thread_id,
           variant=variant, decision=req.decision,
           status="interrupted" if interrupts else "ok")
    if interrupts:
        return ChatResponse(answer="", thread_id=req.thread_id, usage=usage,
                            status="interrupted", interrupt=interrupts[0], variant=variant)
    return ChatResponse(answer=answer, thread_id=req.thread_id, usage=usage, variant=variant)


@app.get("/runs/{{thread_id}}")
def run_state(thread_id: str, authorization: Optional[str] = Header(default=None)):
    """查一条会话当前停在哪：有没有待审批、下一批节点是什么。"""
    _check_auth(authorization)
    try:
        snapshot = graph().get_state({{"configurable": {{"thread_id": thread_id}}}})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, {{"error": str(exc), "thread_id": thread_id}}) from exc
    values = getattr(snapshot, "values", {{}}) or {{}}
    pending = _interrupt_items(getattr(snapshot, "interrupts", ()))
    return {{"thread_id": thread_id,
            "next": list(getattr(snapshot, "next", ()) or ()),
            "answer": values.get("data", ""),
            "status": "interrupted" if pending else "ok",
            "interrupt": pending[0] if pending else None}}


def chat_stream(req: ChatRequest, request: Request,
                authorization: Optional[str] = Header(default=None)):
    _check_auth(authorization)
    trace_id = getattr(request.state, "trace_id", "") or _new_trace_id(None)
    thread_id = req.thread_id or uuid.uuid4().hex[:16]
    _ensure_budget()
    _guard_input(req.message, trace_id, request)
    variant = _pick_variant(request, trace_id)
    request.state.variant = variant

    def gen():
        started = time.time()
        deadline = started + max(1, settings.run_timeout_s)
        interrupted = False
        _acquire_slot(settings.run_timeout_s)
        try:
            flow.reset_usage()
            _bind_trace(trace_id)
            flow.set_canary(variant == "canary")
            yield "event: open\\ndata: " + json.dumps(
                {{"trace_id": trace_id, "thread_id": thread_id, "variant": variant}},
                ensure_ascii=False) + "\\n\\n"
            config = {{"configurable": {{"thread_id": thread_id}}}}
            payload = {{"data": req.message, "user_input": req.message, "route": "",
                       "trace_id": trace_id}}
            for chunk in graph().stream(payload, config=config, stream_mode="updates"):
                if time.time() > deadline:
                    metrics.inc("stream_timeouts")
                    yield "event: error\\ndata: " + json.dumps(
                        {{"error": "run timeout"}}, ensure_ascii=False) + "\\n\\n"
                    return
                node = list(chunk.keys())[0] if isinstance(chunk, dict) and chunk else ""
                if isinstance(chunk, dict) and "__interrupt__" in chunk:
                    interrupted = True
                    body = json.dumps({{"interrupt": _interrupt_items(chunk)[:1]}},
                                      ensure_ascii=False, default=str)
                    yield f"event: interrupt\\ndata: {{body}}\\n\\n"
                body = json.dumps({{"node": node, "update": chunk}},
                                  ensure_ascii=False, default=str)
                yield f"event: update\\ndata: {{body}}\\n\\n"
            usage = _account(flow.take_usage())
            yield "event: usage\\ndata: " + json.dumps(usage, ensure_ascii=False) + "\\n\\n"
            yield "event: done\\ndata: {{}}\\n\\n"
            metrics.inc("stream_ok")
        except Exception as exc:  # noqa: BLE001
            body = json.dumps({{"error": str(exc), "trace_id": trace_id}}, ensure_ascii=False)
            yield f"event: error\\ndata: {{body}}\\n\\n"
            metrics.inc("stream_errors")
            log_event("stream_error", {{"trace_id": trace_id, "error": str(exc)}})
        finally:
            flow.take_usage()
            if not req.thread_id and not interrupted:
                _drop_thread(thread_id)
            _release_slot()
            metrics.observe("stream_latency_ms", (time.time() - started) * 1000)
            metrics.observe(f"stream_latency_{{variant}}", (time.time() - started) * 1000)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={{"X-Trace-Id": trace_id}})


@app.get("/metrics")
def prometheus():
    if not settings.metrics_on:
        raise HTTPException(404, "metrics disabled")
    return PlainTextResponse(metrics.render_prometheus())


@app.get("/metrics/json")
def metrics_json():
    if not settings.metrics_on:
        raise HTTPException(404, "metrics disabled")
    return JSONResponse(metrics.snapshot())


# 入口按「服务设置 → 入口」注册：http / sse / both 决定暴露哪几个，
# entry_path 决定对外路径（/chat 始终保留，方便已有调用方）
def _register_routes() -> None:
    paths = ["/chat"]
    if settings.entry_path and settings.entry_path not in paths:
        paths.append(settings.entry_path)
    for path in paths:
        if settings.entry_mode in ("http", "both"):
            app.add_api_route(path, chat, methods=["POST"], response_model=ChatResponse)
        if settings.entry_mode in ("sse", "both"):
            app.add_api_route(path + "/stream", chat_stream, methods=["POST"])


_register_routes()
'''


def render_dockerfile() -> str:
    return '''FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \\
    PIP_NO_CACHE_DIR=1 \\
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt requirements.lock.txt .
COPY wheels/ ./wheels/
# wheels/ 里有离线包就优先用；空的也无妨，pip 会正常走源
RUN pip install --no-cache-dir --find-links wheels -r requirements.lock.txt

# 非 root 运行：容器被拿下时拿不到宿主写权限
RUN useradd -m -u 10001 appuser

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \\
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
'''


def render_dockerignore() -> str:
    """镜像构建时一定要排除的东西：.env 里的 key 不能被 COPY 进层。"""
    return '''.env
.env.*
.venv/
__pycache__/
*.pyc
*.pyo
*.db
.sessions.db
outputs/*
!outputs/.gitkeep
.git/
.github/
tests/
'''


def render_compose(slug: str) -> str:
    return f'''services:
  {slug or "agent"}:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      MINEAGENT_SESSION_STORE: ${{MINEAGENT_SESSION_STORE:-sqlite}}
    volumes:
      - ./outputs:/app/outputs
      - ./skills:/app/skills
    restart: unless-stopped
    stop_grace_period: 30s
    mem_limit: 1g
    healthcheck:
      test: ["CMD", "python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
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
      - run: pip install --find-links wheels -r requirements.lock.txt
      - run: python -m compileall -q .
      - run: python -m pytest -q
      - run: python settings.py
      - run: python evals/run.py --check
'''


def render_tests(has_graph: bool = True) -> str:
    head = '''"""最小冒烟测试：不需要真实模型，也不联网。"""
from __future__ import annotations

import os

os.environ.setdefault("MINEAGENT_API_KEY", "test-key")
os.environ.setdefault("MINEAGENT_BASE_URL", "http://127.0.0.1:9/v1")
os.environ.setdefault("MINEAGENT_SESSION_STORE", "none")
os.environ.setdefault("MINEAGENT_RESUME", "0")
'''
    if not has_graph:
        # AutoGen / CrewAI / SmolAgents：没有 server.py，只验证入口能导入
        return head + '''

def test_agent_imports():
    import agent

    assert callable(agent.main)


def test_settings_load():
    import settings

    assert settings.settings.project_name
    assert settings.settings.max_concurrency >= 1
'''
    return head + '''

def test_server_imports():
    import server

    assert server.app is not None


def test_health():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    assert client.get("/health").json()["ok"] is True


def test_ready_reports_missing_config():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    body = client.get("/ready").json()
    # 要么就绪，要么明确说出缺哪一项，不能只有一句 false
    assert "missing" in body
    assert "unimplemented" in body


def test_metrics_is_prometheus_text():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")


def test_chat_request_schema():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    # 空 body 必须是 422（参数校验），而不是 500
    assert client.post("/chat", json={}).status_code == 422


def test_trace_id_is_echoed():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    resp = client.post("/chat", json={}, headers={"X-Trace-Id": "t-1"})
    # 参数校验失败也要带回 trace id，排查时才能对上日志
    assert resp.headers.get("X-Trace-Id") == "t-1"


def test_resume_requires_thread_id():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    assert client.post("/resume", json={}).status_code == 422


def test_resume_disabled_returns_501():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    # 冒烟测试里固定 MINEAGENT_RESUME=0：关掉断点续跑时应明确拒绝，而不是假装成功
    resp = client.post("/resume", json={"thread_id": "t", "decision": "approve"})
    assert resp.status_code == 501


def test_run_state_endpoint_exists():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    resp = client.get("/runs/not-started-yet")
    assert resp.status_code in (200, 404)
'''


def render_requirements_extra(session_store: str = "sqlite") -> str:
    lines = [
        "fastapi>=0.110",
        "uvicorn[standard]>=0.29",
        "pydantic>=2.5",
        "pydantic-settings>=2.2",
        "httpx>=0.27",
    ]
    # LangGraph 1.x 把 sqlite / postgres 的 checkpointer 拆成了独立包，
    # 不装的话「会话存储」会静默退化成内存态（重启就丢，审批也接不上）
    if session_store in ("sqlite", "postgres"):
        lines.append("langgraph-checkpoint-sqlite>=2.0")
    if session_store == "postgres":
        lines.append("langgraph-checkpoint-postgres>=2.0")
        lines.append("psycopg[binary]>=3.1")
    lines.append("")
    lines.append("# 测试依赖（生产镜像里可以删掉这一行）")
    lines.append("pytest>=8.0")
    return "\n".join(lines) + "\n"


_REQ_RE = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]+\])?")


def _parse_requirements(text: str) -> List[Tuple[str, str, str]]:
    """把 requirements 文本拆成 (包名, extras, 原始行)。"""
    out: List[Tuple[str, str, str]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _REQ_RE.match(line)
        if not match:
            continue
        out.append((match.group(1), match.group(2) or "", line))
    return out


def render_requirements_lock(requirements_text: str) -> str:
    """把生成环境里能查到的直接依赖钉死版本，供离线 / 可复现安装用。

    查不到的包保留原来的下限写法，并在注释里点名，避免悄悄降级。
    """
    pinned: List[str] = []
    floating: List[str] = []
    for name, extras, line in _parse_requirements(requirements_text):
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            floating.append(line)
            continue
        pinned.append(f"{name}{extras}=={version}")

    header = [
        "# 由 MineAgent 生成：直接依赖的版本锁。",
        "# 目标机可复现安装：pip install -r requirements.lock.txt",
        "# 想重新锁定：python scripts/make_lock.py（在装好依赖的环境里跑）",
        "# 完整传递依赖请用 scripts/offline_bundle.py 打 wheels/ 离线包。",
    ]
    if floating:
        header.append("# 以下包在生成环境里没有安装，保留了版本下限：" + ", ".join(
            line.split(">")[0].split("=")[0] for line in floating))
    return "\n".join(header + [""] + pinned + [""] + floating) + "\n"


_MAKE_LOCK_PY = '''"""重新锁定直接依赖的版本（在装好依赖的环境里执行）。"""
from __future__ import annotations

import importlib.metadata
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REQ = HERE / "requirements.txt"
OUT = HERE / "requirements.lock.txt"
REQ_RE = re.compile(r"^([A-Za-z0-9_.\\-]+)(\\[[^\\]]+\\])?")


def main() -> int:
    pinned, floating = [], []
    for raw in REQ.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = REQ_RE.match(line)
        if not match:
            continue
        name, extras = match.group(1), match.group(2) or ""
        try:
            pinned.append(f"{name}{extras}=={importlib.metadata.version(name)}")
        except importlib.metadata.PackageNotFoundError:
            floating.append(line)
    body = ["# 由 scripts/make_lock.py 生成", ""] + pinned + [""] + floating
    OUT.write_text("\\n".join(body) + "\\n", encoding="utf-8")
    print(f"已写入 {OUT.name}：{len(pinned)} 个包已钉版本，{len(floating)} 个未安装")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


_OFFLINE_BUNDLE_PY = '''"""打离线包：把依赖的 wheel 全部下载到 wheels/，客户机房没外网也能装。

用法（在一台能上网、且 Python 版本与目标机一致的机器上）：
    python scripts/offline_bundle.py
    # 生成 wheels/ 后，连同项目一起拷到目标机：
    #   Linux/macOS:  ./scripts/install_offline.sh
    #   Windows:      .\\\\scripts\\\\install_offline.ps1
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
WHEELS = HERE / "wheels"


def main() -> int:
    WHEELS.mkdir(exist_ok=True)
    req = HERE / "requirements.lock.txt"
    if not req.exists():
        req = HERE / "requirements.txt"
    cmd = [sys.executable, "-m", "pip", "download", "-r", str(req),
           "-d", str(WHEELS), "--only-binary=:all:"]
    print(">>>", " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        # 有包没有 wheel 时退一步：允许源码包（目标机需要有编译工具链）
        print(">>> 纯 wheel 下载失败，改为允许 sdist 重试")
        cmd.remove("--only-binary=:all:")
        cmd.insert(5, "--no-binary=:none:")
        result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"离线包就绪：{WHEELS}（{len(list(WHEELS.iterdir()))} 个文件）")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
'''


_INSTALL_OFFLINE_SH = '''#!/usr/bin/env bash
# 离线安装：依赖都在 wheels/ 里，不联网
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
"$PY" -m pip install --no-index --find-links wheels -r requirements.lock.txt
echo "装好了。启动服务：uvicorn server:app --host 0.0.0.0 --port 8000"
'''


_INSTALL_OFFLINE_PS1 = '''# 离线安装：依赖都在 wheels/ 里，不联网
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$Py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
& $Py -m pip install --no-index --find-links wheels -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw "离线安装失败，检查 wheels/ 是否完整" }
Write-Host "装好了。启动服务：uvicorn server:app --host 0.0.0.0 --port 8000"
'''


_EVAL_RUN_PY = '''"""按用例跑一遍 agent，按规则打分，写出 report.json。

用法：
    python evals/run.py --check        # 只校验用例格式与打分逻辑（不调模型，CI 用）
    python evals/run.py                # 真跑（需要 MINEAGENT_API_KEY）
    python evals/run.py --limit 3      # 只跑前几条
    python evals/run.py --set evals/cases.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_SET = HERE / "cases.jsonl"
CANDIDATES = HERE / "candidates.jsonl"
REPORT = HERE / "report.json"
PASS_RATE = 0.8


def load_candidates(path: Path, limit: int = 0) -> list:
    """线上出错的请求攒在这里；跑一遍看现在还会不会报错，再决定要不要转成正式用例。"""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = str(item.get("input") or "").strip()
        if not text:
            continue
        out.append({"id": f"cand-{len(out) + 1}", "input": text,
                    "expect_contains": [], "expect_not_contains": [],
                    "max_latency_ms": 0, "from_error": item.get("error", "")})
    return out[:limit] if limit else out


def run_candidates(limit: int) -> int:
    items = load_candidates(CANDIDATES, limit)
    if not items:
        print(f"没有待办候选（{CANDIDATES} 还不存在或为空）")
        return 0
    rows = run_real(items)
    still_failing = [r for r in rows if not r["passed"]]
    for row in rows:
        flag = "OK  " if row["passed"] else "FAIL"
        print(f"[{flag}] {row['id']}  {row.get('error') or '不再报错'}")
    print(f"候选 {len(rows)} 条，仍失败 {len(still_failing)} 条")
    print("把不再报错的 input 抄进 cases.jsonl，并补上 expect_contains，就成了正式用例。")
    return 0 if not still_failing else 1


def load_cases(path: Path, limit: int = 0) -> list:
    if not path.exists():
        raise SystemExit(f"找不到用例文件：{path}")
    cases = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path.name} 第 {line_no} 行不是合法 JSON：{exc}")
        case.setdefault("id", f"case-{len(cases) + 1}")
        case.setdefault("input", "")
        case.setdefault("expect_contains", [])
        case.setdefault("expect_not_contains", [])
        case.setdefault("max_latency_ms", 0)
        if not str(case["input"]).strip():
            raise SystemExit(f"{path.name} 里 {case['id']} 的 input 是空的")
        cases.append(case)
    return cases[:limit] if limit else cases


def score(case: dict, answer: str, latency_ms: float) -> dict:
    """规则打分：非空 / 必含关键词 / 禁含关键词 / 延迟上限。"""
    text = (answer or "").strip()
    must = [str(kw) for kw in case.get("expect_contains") or []]
    banned = [str(kw) for kw in case.get("expect_not_contains") or []]
    scores = {
        "non_empty": 1.0 if text else 0.0,
        "contains": (sum(1 for kw in must if kw in text) / len(must)) if must else 1.0,
        "not_contains": 0.0 if any(kw in text for kw in banned) else 1.0,
    }
    limit = int(case.get("max_latency_ms") or 0)
    if limit:
        scores["latency"] = 1.0 if latency_ms <= limit else 0.0
    scores["passed"] = all(value >= 1.0 for value in scores.values())
    return scores


def run_real(cases: list) -> list:
    sys.path.insert(0, str(ROOT))
    import agent  # 框架原生入口；缺依赖时会在这里报错

    rows = []
    for case in cases:
        started = time.time()
        error = ""
        try:
            answer = agent.main(str(case["input"]))
        except Exception as exc:  # noqa: BLE001
            answer, error = "", f"{type(exc).__name__}: {exc}"
        latency = (time.time() - started) * 1000
        scores = score(case, answer, latency)
        rows.append({
            "id": case["id"],
            "passed": bool(scores["passed"]) and not error,
            "latency_ms": round(latency, 1),
            "scores": scores,
            "error": error,
            "answer_preview": (answer or "")[:200],
        })
    return rows


def summarize(rows: list) -> dict:
    total = len(rows) or 1
    passed = sum(1 for row in rows if row["passed"])
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "cases": len(rows),
        "passed": passed,
        "pass_rate": round(passed / total, 4),
        "p95_latency_ms": round(latencies[int(len(latencies) * 0.95)] if latencies else 0, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", dest="case_set", default=str(DEFAULT_SET))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--check", action="store_true",
                        help="只校验用例与打分逻辑，不调用模型")
    parser.add_argument("--candidates", action="store_true",
                        help="跑 evals/candidates.jsonl 里线上出错的请求，看现在还报不报错")
    parser.add_argument("--threshold", type=float, default=PASS_RATE)
    args = parser.parse_args()

    if args.candidates:
        return run_candidates(args.limit)

    cases = load_cases(Path(args.case_set), args.limit)

    if args.check:
        # 不碰模型：只证明用例能被解析、打分函数行为正确
        for case in cases:
            score(case, "", 0.0)
        ok = score({"expect_contains": ["甲"], "expect_not_contains": [], "max_latency_ms": 0},
                   "甲乙", 10.0)["passed"]
        bad = score({"expect_contains": ["甲"], "expect_not_contains": [], "max_latency_ms": 0},
                    "乙", 10.0)["passed"]
        if not ok or bad:
            print("打分逻辑自检失败", file=sys.stderr)
            return 1
        print(f"用例 {len(cases)} 条，格式与打分逻辑自检通过")
        return 0

    rows = run_real(cases)
    summary = summarize(rows)
    REPORT.write_text(json.dumps({"summary": summary, "cases": rows},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    for row in rows:
        flag = "PASS" if row["passed"] else "FAIL"
        print(f"[{flag}] {row['id']}  {row['latency_ms']:>7.1f}ms  {row['error']}")
    print(json.dumps(summary, ensure_ascii=False))
    print(f"报告：{REPORT}")
    return 0 if summary["pass_rate"] >= args.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


_EVAL_README = '''# 评测用例

每行一条 JSON：

```json
{"id": "case-1", "input": "用户会问的问题", "expect_contains": ["必须出现的词"],
 "expect_not_contains": ["不该出现的内容"], "max_latency_ms": 15000, "tags": ["smoke"]}
```

- `expect_contains` 为空时只校验「答非空」；
- `max_latency_ms` 为 0 时不校验延迟；
- 一条用例里所有规则都满足才算 pass。

```bash
python evals/run.py --check     # CI：只校验用例格式与打分逻辑，不调模型
python evals/run.py             # 真跑：需要 MINEAGENT_API_KEY，结果写 evals/report.json
python evals/run.py --limit 3   # 先跑前 3 条看看
```

改完 agent 之后跑一遍，`pass_rate` 掉了就是改坏了——这是这个目录唯一的用途。
'''


_LOADTEST_PY = '''"""压测：交付前跑一遍，给 SLO 验收留证据（只用标准库，不装东西）。

用法：
    python scripts/loadtest.py --url http://127.0.0.1:8000/chat --requests 200 --concurrency 8
    python scripts/loadtest.py --url http://127.0.0.1:8000/chat/stream --stream --requests 50

默认按「p95 ≤ 8000ms、错误率 ≤ 1%」判定，超了返回 1。
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import urllib.error
import urllib.request


def one_request(url: str, payload: bytes, headers: dict, timeout: float, stream: bool):
    started = time.time()
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if stream:
                resp.read(1)  # 只等首字节
            else:
                resp.read()
            return (time.time() - started) * 1000, resp.status, ""
    except urllib.error.HTTPError as exc:
        return (time.time() - started) * 1000, exc.code, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return (time.time() - started) * 1000, 0, type(exc).__name__


def worker(url, payload, headers, timeout, stream, count, results, lock):
    local = []
    for _ in range(count):
        local.append(one_request(url, payload, headers, timeout, stream))
    with lock:
        results.extend(local)


def percentile(values, ratio):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * ratio))
    return round(ordered[idx], 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/chat")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--message", default="用一句话介绍你自己")
    parser.add_argument("--thread-prefix", default="load")
    parser.add_argument("--token", default="", help="服务开了鉴权时填 API Key")
    parser.add_argument("--trace-file", default="", help="把每次请求的延迟写到 JSONL")
    parser.add_argument("--stream", action="store_true", help="测 SSE 首字节延迟")
    parser.add_argument("--slo-p95-ms", type=float, default=8000)
    parser.add_argument("--slo-error-rate", type=float, default=0.01)
    args = parser.parse_args()

    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = "Bearer " + args.token

    per_thread = max(1, args.requests // max(1, args.concurrency))
    total = per_thread * args.concurrency
    results = []
    lock = threading.Lock()
    threads = []
    started = time.time()
    for i in range(args.concurrency):
        payload = json.dumps({"message": args.message,
                              "thread_id": f"{args.thread_prefix}-{i}-{int(started)}"}).encode("utf-8")
        t = threading.Thread(target=worker, daemon=True,
                             args=(args.url, payload, headers, args.timeout, args.stream,
                                   per_thread, results, lock))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - started

    latencies = [r[0] for r in results]
    errors = [r for r in results if r[1] != 200]
    ok = len(results) - len(errors)
    error_rate = len(errors) / max(1, len(results))
    p95 = percentile(latencies, 0.95)
    summary = {
        "url": args.url,
        "requests": len(results),
        "ok": ok,
        "error_rate": round(error_rate, 4),
        "rps": round(len(results) / elapsed, 2) if elapsed else 0,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": p95,
            "p99": percentile(latencies, 0.99),
            "max": round(max(latencies), 1) if latencies else 0,
            "avg": round(statistics.fmean(latencies), 1) if latencies else 0,
        },
        "elapsed_s": round(elapsed, 2),
        "slo": {"p95_ms": args.slo_p95_ms, "error_rate": args.slo_error_rate},
    }

    if args.trace_file:
        import pathlib
        path = pathlib.Path(args.trace_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for latency, status, error in results:
                fh.write(json.dumps({"ts": time.time(), "latency_ms": round(latency, 1),
                                     "status": status, "error": error}) + "\\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    violated = summary["latency_ms"]["p95"] > args.slo_p95_ms or error_rate > args.slo_error_rate
    if errors:
        kinds = {}
        for _, _, err in errors:
            kinds[err] = kinds.get(err, 0) + 1
        print("失败类型：", kinds)
    print("SLO 判定：", "不达标" if violated else "达标")
    return 1 if violated else 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


_ACCEPTANCE_MD = '''# 验收清单（私有化交付）

跑完这一页，客户侧的「能不能上线」通常就有结论了。

## 1. 服务能起来

```bash
python settings.py                 # 配置能解析（密钥打码）
uvicorn server:app --host 0.0.0.0 --port 8000
curl -s localhost:8000/health      # {"ok": true}
curl -s localhost:8000/ready       # ok / missing / unimplemented / sandbox
```

`/ready` 里 `missing` 必须为空；`unimplemented` 列出的开关服务端尚未实现，交付时应向客户说明。

## 2. 功能冒烟

```bash
python -m pytest -q                # 不需要真实模型
python evals/run.py --check        # 用例格式与打分逻辑
python evals/run.py                # 真跑（需要 key），看 pass_rate
```

## 3. SLO（按实际业务改数字）

| 指标 | 目标 | 口径 |
| --- | --- | --- |
| 可用性 | ≥ 99.5% / 月 | `/health` 探活成功率 |
| 首字节延迟 p95 | ≤ 8s | `/chat/stream` 首事件 |
| 整轮延迟 p95 | ≤ 30s | `/chat` 端到端 |
| 错误率 | ≤ 1% | 非 2xx / 总请求 |
| 单轮 token 成本 | ≤ 预算 | 响应里的 `usage` |

压测取数：

```bash
python scripts/loadtest.py --url http://127.0.0.1:8000/chat \\
    --requests 200 --concurrency 8 --slo-p95-ms 30000
python scripts/loadtest.py --url http://127.0.0.1:8000/chat/stream \\
    --stream --requests 50 --slo-p95-ms 8000
```

脚本输出 JSON 摘要，末行是「SLO 判定：达标/不达标」，退出码 0/1，可直接进流水线。

## 4. 可观测

```bash
curl -s localhost:8000/metrics | head          # Prometheus 文本
curl -s localhost:8000/runs/<thread_id>        # 会话停在哪、有没有待审批
```

- 打开 trace 落盘：`MINEAGENT_TRACE_FILE=outputs/traces/{date}.jsonl`
- 接 OTel：`MINEAGENT_OTEL_ENDPOINT=http://collector:4318/v1/traces`，
  需要装 `opentelemetry-sdk opentelemetry-exporter-otlp-proto-http`

## 5. 安全与运维

- 鉴权：`MINEAGENT_AUTH=apikey` + `MINEAGENT_SERVICE_KEY`（`oidc` 尚未实现，会返回 501）
- 沙箱：`MINEAGENT_SANDBOX=restricted`（默认）；要强隔离改成 `container` 并确认机器有 docker
- 镜像：`docker compose up --build`，容器内非 root、带 HEALTHCHECK
- 离线：目标机执行 `./scripts/install_offline.sh`（wheels/ 由 `scripts/offline_bundle.py` 生成）
- 会话：`MINEAGENT_SESSION_STORE=sqlite`（默认，重启可续跑）/ `postgres` / `none`（进程内）

## 6. 交付物核对

- [ ] `requirements.lock.txt` 与 `wheels/` 一致，目标机能离线装
- [ ] `evals/report.json` 里的 pass_rate 达到约定值
- [ ] `scripts/loadtest.py` 的 SLO 判定为达标
- [ ] `docs/acceptance.md` 的检查项逐条勾完
- [ ] 升级/回滚方式已写进交付文档（数据库文件、wheels、镜像 tag）
'''


def render_loadtest() -> Dict[str, str]:
    return {
        "scripts/loadtest.py": _LOADTEST_PY,
        "docs/acceptance.md": _ACCEPTANCE_MD,
    }


_SECRET_STORE_PY = '''"""密钥读取：环境变量优先，没有就去 Vault / 本地文件里找。

默认行为跟以前完全一样（只读环境变量）；私有化现场想用 Vault 或受控文件时，
改 MINEAGENT_SECRETS 即可，业务代码不用动：

    env      （默认）只读环境变量
    file     读 MINEAGENT_SECRETS_FILE 指向的 JSON（建议 0600）
    vault    读 Vault KV v2：MINEAGENT_VAULT_ADDR / _TOKEN / _MOUNT / _PATH

查找顺序默认是「环境变量 → provider」，设 MINEAGENT_SECRETS_PRIORITY=provider 可反过来。
provider 出错只告警一次并退回环境变量，不会让服务起不来。
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_LOCK = threading.Lock()
_CACHE: dict = {}
_WARNED: set = set()
_FILE_STATE: dict = {"mtime": 0.0, "data": {}}


def provider_name() -> str:
    return (os.environ.get("MINEAGENT_SECRETS") or "env").strip().lower()


def _priority() -> str:
    return (os.environ.get("MINEAGENT_SECRETS_PRIORITY") or "env").strip().lower()


def _warn_once(key: str, message: str) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    print(f"[secrets] {message}", flush=True)


def _from_file(name: str) -> str:
    path = (os.environ.get("MINEAGENT_SECRETS_FILE") or "").strip()
    if not path:
        return ""
    target = Path(path)
    if not target.exists():
        _warn_once("file-missing", f"密钥文件不存在：{path}")
        return ""
    with _LOCK:
        try:
            mtime = target.stat().st_mtime
            if mtime != _FILE_STATE["mtime"]:
                _FILE_STATE["data"] = json.loads(target.read_text(encoding="utf-8")) or {}
                _FILE_STATE["mtime"] = mtime
            return str(_FILE_STATE["data"].get(name) or "")
        except Exception as exc:  # noqa: BLE001
            _warn_once("file-error", f"读取密钥文件失败：{exc}")
            return ""


def _from_vault(name: str) -> str:
    addr = (os.environ.get("MINEAGENT_VAULT_ADDR") or "").strip().rstrip("/")
    token = (os.environ.get("MINEAGENT_VAULT_TOKEN") or "").strip()
    if not addr or not token:
        _warn_once("vault-config", "Vault 未配置完整（需要 MINEAGENT_VAULT_ADDR 与 MINEAGENT_VAULT_TOKEN）")
        return ""
    mount = (os.environ.get("MINEAGENT_VAULT_MOUNT") or "secret").strip("/")
    path = (os.environ.get("MINEAGENT_VAULT_PATH") or "mineagent").strip("/")
    url = f"{addr}/v1/{mount}/data/{path}"
    req = urllib.request.Request(url, headers={"X-Vault-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        return str(((payload.get("data") or {}).get("data") or {}).get(name) or "")
    except urllib.error.HTTPError as exc:
        _warn_once(f"vault-http-{exc.code}", f"Vault 返回 {exc.code}（{url}）")
    except Exception as exc:  # noqa: BLE001
        _warn_once("vault-error", f"Vault 不可达：{exc}")
    return ""


def _from_provider(name: str) -> str:
    mode = provider_name()
    if mode in ("file", "json"):
        return _from_file(name)
    if mode in ("vault", "vault-kv", "vault_kv"):
        return _from_vault(name)
    return ""


def get_secret(name: str, default: str = "") -> str:
    """按名字取密钥：环境变量与 provider 按优先级各试一次，都没有就用默认值。"""
    if name in _CACHE:
        return _CACHE[name]
    value = ""
    if _priority() == "provider":
        value = _from_provider(name) or os.environ.get(name, "")
    else:
        value = os.environ.get(name, "") or _from_provider(name)
    if not value:
        value = default
    if value:
        _CACHE[name] = value
    return value


def redact(value: str, keep: int = 4) -> str:
    """日志里只露后几位，别把密钥整条打出去。"""
    value = str(value or "")
    if len(value) <= keep:
        return "****" if value else ""
    return "****" + value[-keep:]


def status() -> dict:
    """给 /ready 看：用的哪种来源、配没配齐（不返回任何密钥值）。"""
    mode = provider_name()
    info = {"provider": mode, "priority": _priority()}
    if mode in ("file", "json"):
        path = (os.environ.get("MINEAGENT_SECRETS_FILE") or "").strip()
        info["path"] = path
        info["usable"] = bool(path) and Path(path).exists()
    elif mode in ("vault", "vault-kv", "vault_kv"):
        info["addr"] = (os.environ.get("MINEAGENT_VAULT_ADDR") or "").strip()
        info["usable"] = bool(info["addr"]) and bool((os.environ.get("MINEAGENT_VAULT_TOKEN") or "").strip())
    else:
        info["usable"] = True
    return info


def trace_only_names() -> list:
    """哪些密钥被真正读出来过（只报名字，方便现场核对配置）。"""
    return sorted(_CACHE)


def _reset_cache() -> None:
    """测试用：清掉缓存，让下一次读取重新走 provider。"""
    with _LOCK:
        _CACHE.clear()
        _WARNED.clear()
        _FILE_STATE["mtime"] = 0.0
        _FILE_STATE["data"] = {}
'''


_SECURITY_PY = '''"""安全三件套：输入护栏、PII 脱敏、审计。开关都来自服务设置。

- guardrail: off / log / block —— 输入过长或像提示词注入时，记一笔或直接拒绝
- pii:       True 时把手机号、身份证、邮箱、银行卡号替换成占位符（响应、日志、候选集都过一遍）
- audit:     True 时把「谁在什么时候做了什么」写进 outputs/audit/<日期>.jsonl

只做规则级检查：它挡不住精心构造的攻击，但能挡住「误把内部提示词贴进聊天框」这类常见事故。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
AUDIT_DIR = HERE / "outputs" / "audit"

_PII_PATTERNS = [
    ("phone", re.compile(r"(?<!\\d)1[3-9]\\d{9}(?!\\d)")),
    ("idcard", re.compile(r"(?<!\\d)\\d{17}[\\dXx](?!\\d)")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}")),
    ("bankcard", re.compile(r"(?<!\\d)\\d{16,19}(?!\\d)")),
]

_INJECTION_HINTS = (
    "忽略以上", "忽略之前", "忽略前面的", "ignore previous", "ignore all previous",
    "disregard the above", "system prompt", "你现在的系统提示", "开发者模式",
    "jailbreak", "越狱", "打印你的提示词", "repeat your instructions",
)


def redact(text: str) -> Tuple[str, List[str]]:
    """把文本里的 PII 换成占位符，返回 (脱敏后文本, 命中类型列表)。"""
    out = text or ""
    hits: List[str] = []
    for name, pattern in _PII_PATTERNS:
        def _mark(match, name=name):
            return f"[{name}]"
        out, count = pattern.subn(_mark, out)
        if count:
            hits.append(f"{name}x{count}")
    return out, hits


def check_input(text: str, max_chars: int = 8000) -> List[str]:
    """返回问题列表；空列表表示通过。"""
    issues: List[str] = []
    value = text or ""
    if max_chars and len(value) > max_chars:
        issues.append(f"输入过长（{len(value)} > {max_chars} 字符）")
    lowered = value.lower()
    for hint in _INJECTION_HINTS:
        if hint in lowered:
            issues.append(f"疑似提示词注入特征：{hint}")
            break
    return issues


def fingerprint(value: str) -> str:
    """审计里记「谁」，只留不可逆指纹，不留原始 token。"""
    raw = (value or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def audit(event: str, fields: Dict[str, Any] | None = None, enabled: bool = True) -> None:
    """写一条审计记录；失败绝不打断业务。"""
    if not enabled:
        return
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        path = AUDIT_DIR / f"{time.strftime('%Y-%m-%d')}.jsonl"
        payload = {"ts": time.time(), "event": event, **(fields or {})}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\\n")
    except OSError:
        pass


def status() -> Dict[str, Any]:
    return {"audit_dir": str(AUDIT_DIR), "pii_rules": [name for name, _ in _PII_PATTERNS]}
'''


def render_security() -> str:
    return _SECURITY_PY


def render_secret_store() -> str:
    return _SECRET_STORE_PY


def render_grafana(spec: Dict[str, Any]) -> Dict[str, str]:
    """可直接 import 的 Grafana 看板：数据源用 ${DS_PROMETHEUS} 变量，导入时选一下即可。"""
    name = spec.get("name") or "agent"
    slug = spec.get("slug") or "agent"
    ds = {"type": "prometheus", "uid": "${DS_PROMETHEUS}"}

    def panel(title: str, exprs: list, unit: str, x: int, y: int, w: int = 12, h: int = 8,
              panel_type: str = "timeseries") -> dict:
        return {
            "type": panel_type,
            "title": title,
            "datasource": ds,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
            "targets": [
                {"datasource": ds, "expr": expr, "legendFormat": expr.split("}")[-1][:40],
                 "refId": chr(ord("A") + i)}
                for i, expr in enumerate(exprs)
            ],
        }

    dashboard = {
        "title": f"{name} · Agent 运行看板",
        "uid": f"mineagent-{slug}"[:40],
        "tags": ["mineagent", "agent"],
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": [{
            "name": "DS_PROMETHEUS", "label": "Prometheus", "type": "datasource",
            "query": "prometheus", "current": {}, "hide": 0,
        }]},
        "panels": [
            panel("请求量（/chat）", ["sum(rate(mineagent_chat_ok_total[5m]))"], "reqps", 0, 0, 8),
            panel("错误数", ["sum(rate(mineagent_chat_errors_total[5m]))"], "reqps", 8, 0, 8),
            panel("延迟 p95", ['mineagent_chat_latency_ms{quantile="0.95"}'], "ms", 16, 0, 8),
            panel("流式请求", ["sum(rate(mineagent_stream_ok_total[5m]))"], "reqps", 0, 8, 8),
            panel("成本（USD/小时）", ["sum(rate(mineagent_cost_usd_total[1h]))"], "currencyUSD",
                  8, 8, 8),
            panel("人工审批", ["sum(rate(mineagent_chat_interrupted_total[5m]))"], "reqps",
                  16, 8, 8),
            panel("预算耗尽次数", ["increase(mineagent_budget_exhausted_total[1h])"], "short",
                  0, 16, 8),
            panel("会话中断/错误", ["sum(rate(mineagent_resume_errors_total[5m]))"], "reqps",
                  8, 16, 8),
            panel("请求延迟分布", ["mineagent_chat_latency_ms_count"], "short", 16, 16, 8),
            panel("主版本 p95", ['mineagent_chat_latency_primary{quantile="0.95"}'], "ms",
                  0, 24, 8),
            panel("灰度 p95", ['mineagent_chat_latency_canary{quantile="0.95"}'], "ms",
                  8, 24, 8),
            panel("灰度流量占比", [
                "sum(rate(mineagent_chat_canary_total[5m])) / "
                "clamp_min(sum(rate(mineagent_chat_ok_total[5m])), 1e-9)"
            ], "percentunit", 16, 24, 8),
            panel("流式 p95（按变体）", [
                'mineagent_stream_latency_primary{quantile="0.95"}',
                'mineagent_stream_latency_canary{quantile="0.95"}',
            ], "ms", 0, 32, 12),
            panel("会话重置 / 断点续跑", [
                "sum(increase(mineagent_session_reset_total[1h]))",
                "sum(increase(mineagent_resume_ok_total[1h]))",
            ], "short", 12, 32, 12),
        ],
    }
    return {"docs/grafana-dashboard.json": json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n"}


_BACKUP_PY = '''"""备份：把运行数据打成一个 tar.gz（恢复见 restore.py，演练见 drill.py）。

包含：VERSION / CHANGELOG.md / .history/ / .sessions.db / .sessions-meta.db /
      .store.db / outputs/ / config.json / agent.json

    python scripts/backup.py                 # 写到 backups/<项目名>-<时间>.tar.gz
    python scripts/backup.py --out /data/bk  # 换目录
    python scripts/backup.py --tag pre-upgrade
"""
from __future__ import annotations

import argparse
import json
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "backups"
INCLUDE_FILES = ["agent.py", "VERSION", "CHANGELOG.md", "agent.json", "config.json",
                 "requirements.txt", "requirements.lock.txt", "integrations.json"]
INCLUDE_DIRS = [".history", "outputs", "skills"]
INCLUDE_GLOBS = [".sessions.db", ".sessions-meta.db", ".store.db", "integrations.json"]
SKIP_PARTS = {"__pycache__", ".venv", "backups", "wheels", "node_modules"}


def _collect() -> list:
    items = []
    for name in INCLUDE_FILES:
        p = ROOT / name
        if p.exists():
            items.append(p)
    for name in INCLUDE_DIRS:
        p = ROOT / name
        if p.exists():
            items.extend(x for x in p.rglob("*") if x.is_file())
    for pattern in INCLUDE_GLOBS:
        items.extend(p for p in ROOT.glob(pattern) if p.is_file())
    return [p for p in items if not (set(p.relative_to(ROOT).parts) & SKIP_PARTS)]


def make_backup(out_dir: Path, tag: str = "") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = f"-{tag}" if tag else ""
    archive = out_dir / f"{ROOT.name}-{stamp}{suffix}.tar.gz"
    files = _collect()
    with tarfile.open(archive, "w:gz") as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(ROOT)))
    # 写完立刻回读校验：能列出同样多的条目才算成功
    with tarfile.open(archive, "r:gz") as tar:
        entries = tar.getnames()
    if len(entries) < len(files):
        raise SystemExit(f"备份校验失败：写入 {len(files)} 个文件，回读到 {len(entries)} 个")
    return {"archive": str(archive), "files": len(files), "bytes": archive.stat().st_size,
            "entries": entries[:20]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    info = make_backup(Path(args.out), args.tag)
    print(json.dumps({k: v for k, v in info.items() if k != "entries"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


_RESTORE_PY = '''"""恢复：先用 backup.py 把当前状态留一档，再解开备份覆盖。

    python scripts/restore.py backups/xxx.tar.gz
    python scripts/restore.py backups/xxx.tar.gz --yes    # 跳过确认
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ("agent.py", "VERSION")


def _safe_members(tar: tarfile.TarFile, dest: Path) -> list:
    """只允许解到 dest 里，防止 ../ 之类的路径穿越。"""
    members = []
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if dest.resolve() not in target.parents and target != dest.resolve():
            raise SystemExit(f"备份里有越界路径，拒绝解压：{member.name}")
        members.append(member)
    return members


def restore(archive: Path, assume_yes: bool = False) -> dict:
    archive = archive.resolve()
    if not archive.exists():
        raise SystemExit(f"找不到备份：{archive}")
    with tempfile.TemporaryDirectory(prefix="restore-") as tmp:
        tmp_path = Path(tmp)
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(tmp_path, members=_safe_members(tar, tmp_path))
        names = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
        missing = [name for name in REQUIRED if name not in names]
        if missing:
            raise SystemExit(f"备份不完整，缺少：{', '.join(missing)}")
        if not assume_yes:
            answer = input(f"将用 {archive.name} 覆盖当前数据（先自动备份现状），继续？[y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                return {"restored": False, "reason": "用户取消"}
        pre = json.loads(_run_backup(Path(ROOT / "backups"), "pre-restore"))
        for item in sorted(tmp_path.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(tmp_path)
            target = ROOT / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)
        for cache in ROOT.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
        return {"restored": True, "archive": archive.name, "files": len(names),
                "pre_restore_backup": pre.get("archive")}


def _run_backup(out_dir: Path, tag: str) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    import backup  # noqa: PLC0415

    return json.dumps(backup.make_backup(out_dir, tag), ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    info = restore(Path(args.archive), args.yes)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if info.get("restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


_DRILL_PY = '''"""灾备演练：在临时副本上跑「备份 → 破坏 → 恢复 → 自检」，不碰当前数据。

    python scripts/drill.py            # 退出码 0 表示演练通过
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"__pycache__", ".venv", "backups", "wheels", "node_modules", ".git"}


def _copy_project(dest: Path) -> None:
    for item in ROOT.iterdir():
        if item.name in SKIP:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(*SKIP))
        else:
            shutil.copyfile(item, target)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def main() -> int:
    steps = []
    with tempfile.TemporaryDirectory(prefix="drill-") as tmp:
        work = Path(tmp) / "project"
        work.mkdir()
        _copy_project(work)
        agent = work / "agent.py"
        before = _sha(agent)

        r = _run(work, "scripts/backup.py")
        steps.append({"step": "backup", "ok": r.returncode == 0, "out": (r.stdout or "").strip()[:120]})
        archives = sorted((work / "backups").glob("*.tar.gz"))
        if not archives:
            print(json.dumps({"passed": False, "steps": steps}, ensure_ascii=False, indent=2))
            return 1

        # 破坏：改写 agent.py、清掉会话库
        agent.write_text("# 演练：故意写坏\\n", encoding="utf-8")
        for db in (".sessions.db", ".sessions-meta.db"):
            (work / db).unlink(missing_ok=True)

        r = _run(work, "scripts/restore.py", str(archives[-1]), "--yes")
        steps.append({"step": "restore", "ok": r.returncode == 0, "out": (r.stdout or "").strip()[:120]})
        after = _sha(agent)
        steps.append({"step": "verify-agent", "ok": before == after,
                      "before": before, "after": after})
        checks = {
            "VERSION": (work / "VERSION").exists(),
            "CHANGELOG": (work / "CHANGELOG.md").exists(),
            "outputs": (work / "outputs").exists(),
        }
        steps.append({"step": "verify-files", "ok": all(checks.values()), "detail": checks})

    passed = all(item["ok"] for item in steps)
    print(json.dumps({"passed": passed, "steps": steps}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


_RUNBOOK_MD = '''# 运维手册

假设项目目录为 `/opt/mineagent-agent`，服务跑在 8000。

## 启动 / 停止 / 重启

```bash
cd /opt/mineagent-agent
./scripts/install_offline.sh                 # 首次：离线装依赖
uvicorn server:app --host 0.0.0.0 --port 8000 &
curl -s localhost:8000/ready                 # ok=true 才算起来了
kill $(cat server.pid)                        # 停止（建议用 systemd / compose 托管）
```

## 健康检查

| 接口 | 用途 | 期望 |
| --- | --- | --- |
| `/health` | 存活 + 版本 | `{"ok":true,"version":"1.0.3"}` |
| `/ready` | 就绪（缺配置 / 未实现项 / 沙箱 / 密钥 / 安全） | `missing` 为空 |
| `/metrics` | Prometheus 指标 | 文本，含 `mineagent_chat_ok_total` |
| `/version` | 当前生成物版本记录 | version / hash / generated_at |

## 备份

```bash
python scripts/backup.py                 # → backups/<项目>-<时间>.tar.gz
python scripts/backup.py --tag pre-upgrade
```

包含：`VERSION`、`CHANGELOG.md`、`.history/`、会话库、`.store.db`、`outputs/`、`config.json`、`agent.json`。
写完会回读校验条目数，数量不符会直接报错。

建议：**升级前、改配置前、批量导入数据前**各做一次；用 cron 每天一次并保留 7 天。

## 恢复

```bash
python scripts/restore.py backups/xxx.tar.gz        # 会先自动备份当前状态再覆盖
```

恢复前会检查备份里是否含 `agent.py` 与 `VERSION`；解压路径有越界会直接拒绝。

## 灾备演练（交付前必做）

```bash
python scripts/drill.py        # 退出码 0 = 通过
```

它在临时副本里做一遍「备份 → 写坏 agent.py、删会话库 → 恢复 → 核对哈希与文件」，
**不碰生产数据**。把这个命令写进季度检查清单。

## 回滚到上一版生成物

```bash
curl -s localhost:8000/runs                               # 看会话状态
curl -s localhost:8000/api/canvases/<id>/versions         # 列版本（平台侧）
cp .history/agent-1.0.2.py agent.py                        # 或者直接在项目里换文件
```

改完 `agent.py` 后重启服务；`.history/` 里保留最近 5 版，回滚前记得先 `backup.py`。

## 常见故障

| 现象 | 先看 | 处理 |
| --- | --- | --- |
| 起不来，打印「服务配置校验失败」 | 那行错误的字段名 | 按 `.env.example` 改对应环境变量 |
| `/ready` 里 `missing` 非空 | 缺模型 key 或 base_url | 配 `MINEAGENT_API_KEY` / `MINEAGENT_BASE_URL` |
| 401 | 鉴权 | 检查 `MINEAGENT_AUTH` 与 `MINEAGENT_SERVICE_KEY` |
| 429 | 预算或并发 | 看 `/metrics` 的 `budget_exhausted_total`、调 `MAX_CONCURRENCY` |
| 501 | 断点续跑关着 | `MINEAGENT_RESUME=1` |
| 409 | 没有待审批 | 先 `/chat` 触发挂起，再 `/resume` |
| 延迟飙高 | `/metrics` p95 + `docs/grafana-dashboard.json` | 看是模型慢还是节点多，必要时开 `TRACE_FILE` 定位 |

## 扩容

- 会话存 Postgres（`MINEAGENT_SESSION_STORE=postgres` + `DATABASE_URL`）后可多副本
- 多副本时 `MAX_CONCURRENCY` 按副本数分摊；`BUDGET_USD` 是**进程内**累计，多副本下不等于全局预算
- `/metrics` 由各副本各自暴露，由 Prometheus 抓取汇总
'''


def render_ops_scripts() -> Dict[str, str]:
    return {
        "scripts/backup.py": _BACKUP_PY,
        "scripts/restore.py": _RESTORE_PY,
        "scripts/drill.py": _DRILL_PY,
        "docs/runbook.md": _RUNBOOK_MD,
    }


def render_evals(spec: Dict[str, Any]) -> Dict[str, str]:
    """评测目录：用例模板 + 打分脚本 + 说明。"""
    inputs = [n for n in spec.get("nodes", []) if (n.get("kind") or "") == "input"]
    rows = []
    for idx, node in enumerate(inputs or [{"params": {}}], 1):
        params = node.get("params") or {}
        text = str(params.get("value") or params.get("default")
                   or params.get("example") or "").strip()
        rows.append(json.dumps({
            "id": f"case-{idx}",
            "input": text or "把这里换成一条真实的用户问题",
            "expect_contains": [],
            "expect_not_contains": [],
            "max_latency_ms": 15000,
            "tags": ["smoke"],
        }, ensure_ascii=False))
    body = "# 每行一个用例；字段说明见 README.md\n" + "\n".join(rows) + "\n"
    return {
        "evals/cases.jsonl": body,
        "evals/run.py": _EVAL_RUN_PY,
        "evals/README.md": _EVAL_README,
    }


def render_lock_files(requirements_text: str) -> Dict[str, str]:
    """锁文件 + 离线安装脚本。"""
    return {
        "requirements.lock.txt": render_requirements_lock(requirements_text),
        "scripts/make_lock.py": _MAKE_LOCK_PY,
        "scripts/offline_bundle.py": _OFFLINE_BUNDLE_PY,
        "scripts/install_offline.sh": _INSTALL_OFFLINE_SH,
        "scripts/install_offline.ps1": _INSTALL_OFFLINE_PS1,
    }


def render_production_files(spec: Dict[str, Any], graph: Dict[str, Any],
                            framework: str, requirements_text: str = "",
                            has_graph: bool = False) -> Dict[str, str]:
    """返回需要写进项目的生产化文件。

    框架无关的一律生成（配置 / 日志 / 锁 / 评测 / CI）；
    只有真生成了 build_graph 的项目才额外生成 server.py 与镜像文件。
    """
    has_graph = bool(has_graph)
    svc = merge_service(graph.get("service"))
    files: Dict[str, str] = {
        "secret_store.py": render_secret_store(),
        "security.py": render_security(),
        "settings.py": render_settings(spec, svc),
        "telemetry.py": render_telemetry(),
        "checkpoint.py": render_checkpoint(),
        ".dockerignore": render_dockerignore(),
        "wheels/.gitkeep": "# 离线包目录：scripts/offline_bundle.py 会把 wheel 下到这里\n",
        ".github/workflows/ci.yml": render_ci(),
        "tests/test_smoke.py": render_tests(has_graph),
        # 外部数据 / 评测中台：只生成连接器与评测脚本，不做中台本体
        "integrations/__init__.py": '"""外部数据 / 评测中台连接器（由画布的「服务设置」生成）。"""\n',
        "integrations/data_client.py": render_data_client(),
        "integrations/eval_client.py": render_eval_client(),
        "integrations/eval_run.py": render_eval_run(spec),
        "integrations.json": render_integrations_json(svc),
    }
    # 服务入口 / 镜像只对「图」项目有意义：AutoGen、CrewAI、SmolAgents 没有 build_graph，
    # 生成 uvicorn server:app 只会得到一个起不来的镜像
    if has_graph:
        files["server.py"] = render_server(spec)
        files["Dockerfile"] = render_dockerfile()
        files["docker-compose.yml"] = render_compose(spec.get("slug") or "")
    # 锁版本 + 离线安装：私有化交付的基本盘
    if requirements_text:
        files.update(render_lock_files(requirements_text))
    # 评测用例 + 打分脚本：改完 agent 用它证明没变差
    files.update(render_evals(spec))
    # 压测脚本 + 验收清单 + Grafana 看板：只有 HTTP 服务才有意义
    if has_graph:
        files.update(render_loadtest())
        files.update(render_grafana(spec))
    # 备份 / 恢复 / 演练 + 运维手册：任何项目都该有
    files.update(render_ops_scripts())
    return files
