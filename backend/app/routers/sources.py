"""源码来源：上传压缩包 / GitHub 地址 / 本地目录，然后静态扫描出架构线索。

扫描结果给 AI 助手做「从源码还原架构」，不直接生成画布——
归纳成节点图那一步交给模型（它比规则擅长）。
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import source_fetch, source_scan

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _scan_or_400(source_id: str) -> Dict[str, Any]:
    try:
        root = source_fetch.resolve_dir(source_id)
        if not root.is_dir():
            raise source_fetch.SourceError(f"源码目录不存在：{root}")
        result = source_scan.scan(root)
    except source_fetch.SourceError as exc:
        raise HTTPException(400, str(exc)) from exc
    meta = source_fetch.load_meta(source_id) or {}
    result["source"] = {"id": source_id, "kind": meta.get("kind"),
                        "label": meta.get("label")}
    return result


@router.get("")
def list_sources():
    return {"sources": source_fetch.list_sources()}


@router.post("/upload")
async def upload_source(file: UploadFile = File(...)):
    data = await file.read()
    try:
        source_id = source_fetch.from_upload(file.filename or "upload.zip", data)
    except source_fetch.SourceError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "source_id": source_id,
            "source": source_fetch.load_meta(source_id)}


@router.post("/github")
def add_github(payload: Dict[str, Any]):
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "缺少仓库地址")
    try:
        source_id = source_fetch.from_github(url)
    except source_fetch.SourceError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "source_id": source_id,
            "source": source_fetch.load_meta(source_id)}


@router.post("/local")
def add_local(payload: Dict[str, Any]):
    try:
        source_id = source_fetch.from_local(str(payload.get("path") or ""))
    except source_fetch.SourceError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "source_id": source_id,
            "source": source_fetch.load_meta(source_id)}


@router.get("/{source_id}/scan")
def scan_source(source_id: str):
    return _scan_or_400(source_id)


@router.delete("/{source_id}")
def delete_source(source_id: str):
    if not source_fetch.remove_source(source_id):
        raise HTTPException(404, "源码包不存在")
    return {"ok": True}
