"""画布 CRUD + 保存落盘。"""
from __future__ import annotations

import json
import shutil
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from ..codegen import generate_project, unique_slug
from ..config import PROJECTS_DIR
from ..db import get_conn, get_setting, now_iso, set_setting
from ..framework_templates import FRAMEWORK_INDEX, build_graph
from ..schemas import (CanvasCreate, CanvasDetail, CanvasSummary, CanvasUpdate,
                       GlobalSettings, Graph, ModelConfig, SaveResult)
from ..security import decrypt, encrypt, mask

router = APIRouter(prefix="/api/canvases", tags=["canvases"])


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _row_to_config(row) -> Dict[str, Any]:
    try:
        raw = json.loads(row["model_config"] or "{}")
    except Exception:
        raw = {}
    cipher = raw.pop("api_key_cipher", "")
    return {
        "provider": raw.get("provider", "openai"),
        "base_url": raw.get("base_url", ""),
        "model": raw.get("model", ""),
        "temperature": raw.get("temperature", 0.3),
        "max_tokens": raw.get("max_tokens", 2048),
        "api_key": None,
        "api_key_mask": mask(decrypt(cipher)) if cipher else "",
    }


def _summary(row) -> CanvasSummary:
    graph = json.loads(row["graph"] or "{}")
    return CanvasSummary(
        id=row["id"], name=row["name"], slug=row["slug"], framework=row["framework"],
        node_count=len(graph.get("nodes", [])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _detail(row) -> CanvasDetail:
    graph = json.loads(row["graph"] or "{}")
    return CanvasDetail(
        **_summary(row).model_dump(),
        graph=Graph(**graph),
        llm_config=ModelConfig(**_row_to_config(row)),
    )


def _fetch(conn, canvas_id: str):
    row = conn.execute("SELECT * FROM canvases WHERE id = ?", (canvas_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "画布不存在")
    return row


def _global_defaults() -> Dict[str, Any]:
    return {
        "provider": get_setting("orchestrator_provider", "openai"),
        "base_url": get_setting("orchestrator_base_url", ""),
        "model": get_setting("orchestrator_model", ""),
    }


def resolve_runtime_model(canvas_row) -> Dict[str, Any]:
    """运行/生成时用的模型配置：画布配置优先，缺的回退到全局。"""
    cfg = _row_to_config(canvas_row)
    glob = _global_defaults()
    try:
        raw = json.loads(canvas_row["model_config"] or "{}")
    except Exception:
        raw = {}
    api_key = decrypt(raw.get("api_key_cipher", ""))
    if not api_key:
        api_key = decrypt(get_setting("orchestrator_api_key_cipher", ""))
    return {
        "provider": cfg["provider"] if cfg.get("model") else glob["provider"],
        "base_url": cfg["base_url"] or glob["base_url"] or "https://api.openai.com/v1",
        "model": cfg["model"] or glob["model"] or "gpt-4o-mini",
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
        "api_key": api_key,
    }


def save_canvas(row, graph: Dict[str, Any]) -> tuple[str, List[str]]:
    """把图写入数据库并把代码落到 projects/<slug>/。"""
    cfg = resolve_runtime_model(row)
    project_dir, files = generate_project(
        name=row["name"], slug=row["slug"], framework=row["framework"],
        graph=graph, model_config=cfg,
    )
    return str(project_dir), files


def _persist(conn, canvas_id: str, graph: Dict[str, Any], touch: bool = True) -> Dict[str, Any]:
    row = _fetch(conn, canvas_id)
    project_dir, files = save_canvas(row, graph)
    if touch:
        conn.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now_iso(), canvas_id))
    return {"project_dir": project_dir, "files": files}


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #
@router.get("", response_model=List[CanvasSummary])
def list_canvases():
    with get_conn() as conn:
        # 最近改动过的排前面，打开应用就是上次在用的画布
        rows = conn.execute(
            "SELECT * FROM canvases ORDER BY updated_at DESC, created_at DESC"
        ).fetchall()
    return [_summary(r) for r in rows]


@router.post("", response_model=CanvasDetail)
def create_canvas(payload: CanvasCreate):
    framework = payload.framework if payload.framework in FRAMEWORK_INDEX else "langchain"
    name = (payload.name or "").strip() or "未命名画布"
    graph = build_graph(framework)
    canvas_id = __import__("uuid").uuid4().hex

    with get_conn() as conn:
        slug = unique_slug(name, lambda s: conn.execute(
            "SELECT 1 FROM canvases WHERE slug = ?", (s,)).fetchone() is not None)
        ts = now_iso()
        default_model = {
            "provider": get_setting("orchestrator_provider", "openai"),
            "base_url": get_setting("orchestrator_base_url", ""),
            "model": get_setting("orchestrator_model", ""),
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        conn.execute(
            "INSERT INTO canvases(id,name,slug,framework,graph,model_config,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (canvas_id, name, slug, framework, json.dumps(graph, ensure_ascii=False),
             json.dumps(default_model, ensure_ascii=False), ts, ts),
        )
        row = _fetch(conn, canvas_id)
        try:
            _persist(conn, canvas_id, graph, touch=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"生成项目代码失败：{exc}") from exc
        row = _fetch(conn, canvas_id)
    return _detail(row)


@router.get("/{canvas_id}", response_model=CanvasDetail)
def get_canvas(canvas_id: str):
    with get_conn() as conn:
        return _detail(_fetch(conn, canvas_id))


@router.patch("/{canvas_id}", response_model=CanvasDetail)
def update_canvas(canvas_id: str, payload: CanvasUpdate):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        fields: Dict[str, Any] = {}

        if payload.name is not None:
            new_name = payload.name.strip() or row["name"]
            if new_name != row["name"]:
                fields["name"] = new_name
                # 目录跟着改名
                old_dir = PROJECTS_DIR / row["slug"]
                new_slug = unique_slug(new_name, lambda s: s != row["slug"] and conn.execute(
                    "SELECT 1 FROM canvases WHERE slug = ?", (s,)).fetchone() is not None)
                if new_slug != row["slug"]:
                    new_dir = PROJECTS_DIR / new_slug
                    if old_dir.exists() and not new_dir.exists():
                        shutil.move(str(old_dir), str(new_dir))
                    fields["slug"] = new_slug

        graph_dict: Optional[Dict[str, Any]] = None
        if payload.framework is not None and payload.framework != row["framework"]:
            if payload.framework not in FRAMEWORK_INDEX:
                raise HTTPException(400, f"不支持的框架：{payload.framework}")
            fields["framework"] = payload.framework
            graph_dict = build_graph(payload.framework)
            fields["graph"] = json.dumps(graph_dict, ensure_ascii=False)

        if payload.graph is not None:
            graph_dict = payload.graph.model_dump()
            fields["graph"] = json.dumps(graph_dict, ensure_ascii=False)

        if payload.llm_config is not None:
            old = json.loads(row["model_config"] or "{}")
            new = payload.llm_config.model_dump()
            cipher = old.get("api_key_cipher", "")
            api_key = new.pop("api_key", None)
            new.pop("api_key_mask", None)
            if api_key is not None:
                cipher = encrypt(api_key) if api_key.strip() else ""
            new["api_key_cipher"] = cipher
            fields["model_config"] = json.dumps(new, ensure_ascii=False)

        if not fields:
            return _detail(row)

        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE canvases SET {sets}, updated_at = ? WHERE id = ?",
                     (*fields.values(), now_iso(), canvas_id))
        row = _fetch(conn, canvas_id)

        if graph_dict is not None:
            try:
                _persist(conn, canvas_id, graph_dict, touch=False)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(500, f"落盘失败：{exc}") from exc
        elif "model_config" in fields or "name" in fields or "slug" in fields:
            graph_dict = json.loads(row["graph"] or "{}")
            try:
                _persist(conn, canvas_id, graph_dict, touch=False)
            except Exception:  # noqa: BLE001
                pass
        row = _fetch(conn, canvas_id)
    return _detail(row)


@router.post("/{canvas_id}/save", response_model=SaveResult)
def save_canvas_endpoint(canvas_id: str, graph: Graph):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        graph_dict = graph.model_dump()
        conn.execute("UPDATE canvases SET graph = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(graph_dict, ensure_ascii=False), now_iso(), canvas_id))
        try:
            result = _persist(conn, canvas_id, graph_dict, touch=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"落盘失败：{exc}") from exc
        row = _fetch(conn, canvas_id)
    return SaveResult(ok=True, canvas=_detail(row),
                      project_dir=result["project_dir"], written_files=result["files"])


@router.delete("/{canvas_id}")
def delete_canvas(canvas_id: str):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        conn.execute("DELETE FROM canvases WHERE id = ?", (canvas_id,))
        conn.execute("DELETE FROM runs WHERE canvas_id = ?", (canvas_id,))
    target = (PROJECTS_DIR / row["slug"]).resolve()
    if target.parent == PROJECTS_DIR.resolve() and target.exists():
        shutil.rmtree(target, ignore_errors=True)
    return {"ok": True}
