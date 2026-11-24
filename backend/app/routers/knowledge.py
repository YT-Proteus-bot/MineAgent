"""知识库接口：全局创建、上传文件、建索引、测试检索。

知识库不属于某张画布，画布通过 collection 名引用它。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import knowledge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except knowledge.KnowledgeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        # 兜底：别让前端只看到一句「500 Internal Server Error」，
        # 把真实原因带出去，同时把堆栈打进后端日志。
        logger.exception("知识库操作失败：%s", getattr(fn, "__name__", fn))
        raise HTTPException(
            500, f"服务端内部错误：{type(exc).__name__}: {exc}") from exc


@router.get("")
def list_knowledge():
    return {"items": knowledge.list_kbs()}


@router.post("")
def create_knowledge(payload: Dict[str, Any]):
    kb = _wrap(knowledge.create_kb, payload)
    return {"ok": True, "kb": kb}


@router.get("/{kb_id}")
def get_knowledge(kb_id: str):
    kb = knowledge.get_kb(kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    kb["files"] = knowledge.list_files(kb_id)
    return {"kb": kb}


@router.patch("/{kb_id}")
def update_knowledge(kb_id: str, payload: Dict[str, Any]):
    return {"ok": True, "kb": _wrap(knowledge.update_kb, kb_id, payload)}


@router.delete("/{kb_id}")
def delete_knowledge(kb_id: str):
    if not knowledge.delete_kb(kb_id):
        raise HTTPException(404, "知识库不存在")
    return {"ok": True}


@router.post("/{kb_id}/files")
async def upload_file(kb_id: str, file: UploadFile = File(...)):
    data = await file.read()
    item = _wrap(knowledge.save_file, kb_id, file.filename or "file", data)
    return {"ok": True, "file": item, "files": knowledge.list_files(kb_id)}


@router.delete("/{kb_id}/files")
def delete_file(kb_id: str, name: str):
    if not knowledge.delete_file(kb_id, name):
        raise HTTPException(404, "文件不存在")
    return {"ok": True, "files": knowledge.list_files(kb_id)}


@router.post("/{kb_id}/build")
def build_knowledge(kb_id: str):
    """同步建索引。文件不多时几秒到几十秒，前端显示进度即可。"""
    return _wrap(knowledge.build, kb_id)


@router.get("/{kb_id}/search")
def search_knowledge(kb_id: str, q: str, top_k: int = 5):
    hits = _wrap(knowledge.search, kb_id, q, top_k)
    return {"ok": True, "hits": hits}
