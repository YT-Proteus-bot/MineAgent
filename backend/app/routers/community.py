"""社区模板路由：GitHub 连接、发布 PR、模板列表与加载。"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import community
from ..codegen import unique_slug
from ..config import PROJECTS_DIR
from ..db import get_conn, get_setting, now_iso, set_setting
from ..schemas import CanvasBackground, Graph
from ..security import decrypt, encrypt, mask
from .canvases import _detail, _fetch, _persist

router = APIRouter(prefix="/api/community", tags=["community"])
oauth_router = APIRouter(prefix="/api/github", tags=["community"])

STATE_TTL = 600


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/config")
def read_config(request: Request):
    conf = community.cfg()
    secret = decrypt(get_setting("github_client_secret_cipher", ""))
    return {
        "repo": conf["repo"],
        "branch": conf["branch"],
        "dir": conf["dir"],
        "client_id": conf["client_id"],
        "client_secret_mask": mask(secret) if secret else "",
        "connected": conf["connected"],
        "login": conf["login"],
        "configured": bool(conf["repo"] and conf["client_id"] and secret),
        "callback_url": f"{_base_url(request)}/api/github/callback",
    }


@router.put("/config")
def write_config(payload: Dict[str, Any]):
    repo = str(payload.get("repo") or "").strip()
    if repo:
        try:
            community.parse_repo(repo)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    set_setting("community_repo", repo)
    set_setting("community_branch", str(payload.get("branch") or "main").strip() or "main")
    set_setting("community_dir", str(payload.get("dir") or "templates").strip().strip("/") or "templates")
    set_setting("github_client_id", str(payload.get("client_id") or "").strip())
    secret = payload.get("client_secret")
    if secret is not None:
        set_setting("github_client_secret_cipher", encrypt(str(secret).strip()) if str(secret).strip() else "")
    return {"ok": True}


@router.get("/auth/url")
def auth_url(request: Request):
    state = uuid.uuid4().hex
    set_setting("github_oauth_state", state)
    set_setting("github_oauth_state_at", str(int(time.time())))
    try:
        url = community.oauth_authorize_url(_base_url(request), state)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"url": url, "state": state}


@oauth_router.get("/callback")
def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    base = _base_url(request)
    if error:
        return RedirectResponse(f"{base}/?github=error&reason={error}", status_code=302)
    saved_state = get_setting("github_oauth_state", "")
    saved_at = int(get_setting("github_oauth_state_at", "0") or 0)
    if not code or not state or state != saved_state or time.time() - saved_at > STATE_TTL:
        return RedirectResponse(f"{base}/?github=error&reason=state", status_code=302)
    try:
        access = community.exchange_code(code)
        user = community.github_user(access)
    except Exception:  # noqa: BLE001
        return RedirectResponse(f"{base}/?github=error&reason=exchange", status_code=302)
    set_setting("github_token_cipher", encrypt(access))
    set_setting("github_login", str(user.get("login") or ""))
    set_setting("github_oauth_state", "")
    return RedirectResponse(f"{base}/?github=connected", status_code=302)


@router.post("/disconnect")
def disconnect():
    set_setting("github_token_cipher", "")
    set_setting("github_login", "")
    return {"ok": True}


@router.post("/publish")
def publish(payload: Dict[str, Any]):
    canvas_id = str(payload.get("canvas_id") or "")
    if not canvas_id:
        raise HTTPException(400, "缺少 canvas_id")
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        graph = json.loads(row["graph"] or "{}")

    project_dir = PROJECTS_DIR / row["slug"]
    if not project_dir.exists():
        try:
            with get_conn() as conn:
                _persist(conn, canvas_id, graph, touch=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"生成项目文件失败：{exc}") from exc

    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
    meta = {
        "slug": "",
        "name": str(payload.get("name") or row["name"]).strip(),
        "description": str(payload.get("description") or "").strip()[:1000],
        "tags": [str(t)[:30] for t in tags][:8],
        "author": str(payload.get("author") or "").strip()[:60],
        "framework": row["framework"],
        "mode": row["mode"] or "",
        "node_count": len(graph.get("nodes") or []),
        "created_at": now_iso(),
    }
    try:
        result = community.publish(row, graph, meta, project_dir)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except community.GitHubError as exc:
        raise HTTPException(502, str(exc)) from exc
    return result


@router.get("/templates")
def templates():
    conf = community.cfg()
    if not conf["repo"]:
        return {"ok": True, "configured": False, "templates": []}
    return {"ok": True, "configured": True, "templates": community.list_templates()}


@router.post("/load")
def load_template(payload: Dict[str, Any]):
    slug = str(payload.get("slug") or "").strip()
    if not slug:
        raise HTTPException(400, "缺少模板 slug")
    try:
        data = community.fetch_template(slug)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except community.GitHubError as exc:
        raise HTTPException(502, f"下载模板失败：{exc}") from exc

    meta = data["meta"]
    try:
        graph = Graph(**data["graph"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"模板画布格式不合法：{exc}") from exc
    graph_dict = graph.model_dump()
    graph_dict["background"] = CanvasBackground().model_dump()

    name = str(meta.get("name") or slug).strip() or slug
    framework = str(meta.get("framework") or "langchain")
    canvas_id = uuid.uuid4().hex
    with get_conn() as conn:
        display = f"{name}（社区）"
        final_slug = unique_slug(display, lambda s: conn.execute(
            "SELECT 1 FROM canvases WHERE slug = ?", (s,)).fetchone() is not None)
        ts = now_iso()
        default_model = {
            "provider": get_setting("orchestrator_provider", "deepseek"),
            "base_url": get_setting("orchestrator_base_url", ""),
            "model": get_setting("orchestrator_model", ""),
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        conn.execute(
            "INSERT INTO canvases(id,name,slug,framework,graph,model_config,background,mode,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (canvas_id, display, final_slug, framework,
             json.dumps(graph_dict, ensure_ascii=False),
             json.dumps(default_model, ensure_ascii=False),
             json.dumps(graph_dict["background"], ensure_ascii=False),
             str(meta.get("mode") or ""), ts, ts),
        )
        try:
            _persist(conn, canvas_id, graph_dict, touch=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"生成项目代码失败：{exc}") from exc
        row = _fetch(conn, canvas_id)
    return {"ok": True, "canvas": _detail(row)}
