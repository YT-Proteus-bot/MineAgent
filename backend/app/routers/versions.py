"""画布生成物的版本接口：列历史、看 changelog、回滚到某一版。"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from .. import versions as version_store
from ..db import get_conn

router = APIRouter(prefix="/api/canvases", tags=["versions"])


def _slug_of(canvas_id: str) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT slug, name FROM canvases WHERE id = ?", (canvas_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "画布不存在")
    slug = (row["slug"] or "").strip()
    if not slug:
        raise HTTPException(409, "这个画布还没生成过项目，保存一次后再试")
    return slug


@router.get("/{canvas_id}/versions")
def list_versions(canvas_id: str) -> Dict[str, Any]:
    slug = _slug_of(canvas_id)
    try:
        return {"canvas_id": canvas_id, "slug": slug,
                "current": version_store.current(slug),
                "versions": version_store.list_versions(slug),
                "changelog": version_store.changelog(slug)}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{canvas_id}/versions/{version}/rollback")
def rollback(canvas_id: str, version: str) -> Dict[str, Any]:
    slug = _slug_of(canvas_id)
    try:
        result = version_store.rollback(slug, version)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"canvas_id": canvas_id, "slug": slug, **result}
