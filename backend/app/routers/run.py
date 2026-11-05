"""运行画布上的智能体：子进程执行 + SSE 流式回传。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from typing import Any, AsyncIterator, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..config import PROJECTS_DIR, RUN_LOG_DIR, RUN_TIMEOUT
from ..constraints import validate as validate_graph
from ..db import get_conn, now_iso
from ..schemas import RunRequest
from ..security import decrypt
from .canvases import _fetch, _node_key_env, resolve_runtime_model, save_canvas

router = APIRouter(prefix="/api/canvases", tags=["run"])

EVENT_PREFIX = "@@EVENT@@"
DEPENDENCY_HINTS = {
    "langchain": ["langchain", "langchain_openai", "langgraph"],
    "autogen": ["autogen_agentchat", "autogen_ext"],
    "crewai": ["crewai"],
}


def _sse(obj: Dict[str, Any]) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False, default=str) + "\n\n"


def _deps_status(framework: str) -> Dict[str, bool]:
    import importlib.util
    out = {}
    for mod in DEPENDENCY_HINTS.get(framework, []):
        out[mod] = importlib.util.find_spec(mod) is not None
    return out


@router.get("/{canvas_id}/env")
def env_status(canvas_id: str):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
    fw = row["framework"]
    deps = _deps_status(fw)
    cfg = resolve_runtime_model(row)
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "framework": fw,
        "dependencies": deps,
        "all_dependencies_ready": all(deps.values()) if deps else True,
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
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if cfg.get("api_key"):
        env["MINEAGENT_API_KEY"] = cfg["api_key"]
    if cfg.get("base_url"):
        env["MINEAGENT_BASE_URL"] = cfg["base_url"]
    if cfg.get("model"):
        env["MINEAGENT_MODEL"] = cfg["model"]
    node_keys = 0
    for nm in node_models:
        key = decrypt(nm["api_key_cipher"]) if nm["api_key_cipher"] else ""
        if key:
            env[_node_key_env(nm["node_id"])] = key
            node_keys += 1

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
        started = time.time()
        collected: List[Dict[str, Any]] = []
        final_output = ""
        status = "ok"
        errors: List[str] = []

        yield _sse({"event": "prepared", "run_id": run_id, "canvas_id": canvas_id,
                    "project_dir": project_dir, "slug": slug,
                    "has_api_key": bool(cfg.get("api_key")),
                    "model": cfg.get("model"), "framework": row["framework"],
                    "run_mode": run_mode,
                    "entry": os.path.basename(entry_path)})

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, entry_path, "--input", payload.input or "",
                cwd=project_dir, env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception as exc:  # noqa: BLE001
            yield _sse({"event": "error", "message": f"启动执行进程失败：{exc}"})
            yield _sse({"event": "run_end", "status": "error", "message": str(exc),
                        "output": "", "duration_ms": 0})
            return

        log_lines: List[str] = []
        try:
            assert proc.stdout is not None
            while True:
                if time.time() - started > RUN_TIMEOUT:
                    proc.kill()
                    status = "timeout"
                    yield _sse({"event": "error", "message": f"运行超时（>{RUN_TIMEOUT}s），已终止"})
                    break
                raw = await proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if not line:
                    continue
                if line.startswith(EVENT_PREFIX):
                    try:
                        evt = json.loads(line[len(EVENT_PREFIX):])
                    except json.JSONDecodeError:
                        continue
                    evt.setdefault("run_id", run_id)
                    collected.append(evt)
                    if evt.get("event") == "run_end":
                        final_output = evt.get("output", "") or ""
                        status = evt.get("status", "ok")
                    if evt.get("event") == "error":
                        status = "error"
                        errors.append(str(evt.get("message", "")))
                    yield _sse(evt)
                else:
                    if len(log_lines) < 2000:
                        log_lines.append(line)
                    yield _sse({"event": "log", "level": "stdout", "message": line[:2000]})
            await proc.wait()
        except asyncio.CancelledError:
            proc.kill()
            raise
        finally:
            if proc.returncode is None:
                proc.kill()

        duration = int((time.time() - started) * 1000)
        # 走 agent.py 时没有节点级事件，从普通输出里提取最终结果
        if run_mode == "native" and not final_output:
            final_output = _extract_final(log_lines)
            if proc.returncode not in (0, None):
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
                    (run_id, canvas_id, status, payload.input or "", final_output,
                     "; ".join(errors)[:2000], now_iso(), now_iso()),
                )
        except Exception:  # noqa: BLE001
            pass

        yield _sse({"event": "run_end", "status": status, "output": final_output,
                    "duration_ms": duration, "error": "; ".join(errors)[:2000],
                    "run_id": run_id})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
