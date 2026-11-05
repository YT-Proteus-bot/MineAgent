"""画布背景图：上传、读取、移除。

图片统一存在 backend/data/backgrounds/（不进 git），画布 JSON 里只存文件名。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..config import BACKGROUND_DIR, MAX_BACKGROUND_BYTES
from ..db import get_conn, now_iso
from ..schemas import CanvasBackground
from .canvases import _fetch, _row_to_background, remove_background_files

router = APIRouter(tags=["background"])

ALLOWED = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}
MEDIA = {v: v for v in ALLOWED.values()}


def _safe_background_path(filename: str) -> Path:
    if not filename or any(ch in filename for ch in ("/", "\\", "..", "\0")):
        raise HTTPException(400, "非法的文件名")
    path = (BACKGROUND_DIR / filename).resolve()
    if path.parent != BACKGROUND_DIR.resolve():
        raise HTTPException(400, "非法的文件名")
    return path


@router.get("/api/backgrounds/{filename}")
def get_background(filename: str):
    path = _safe_background_path(filename)
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "背景图不存在")
    media = ALLOWED.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "public, max-age=3600"})


@router.post("/api/canvases/{canvas_id}/background-image")
async def upload_background(canvas_id: str, file: UploadFile = File(...)):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        current = _row_to_background(row)

    suffix = Path(file.filename or "image.png").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(400, f"不支持的图片格式：{suffix or '(无扩展名)'}，"
                                 f"可用：{', '.join(sorted(ALLOWED))}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    if len(data) > MAX_BACKGROUND_BYTES:
        raise HTTPException(413, f"图片太大（{len(data) // 1024 // 1024}MB），上限 "
                                 f"{MAX_BACKGROUND_BYTES // 1024 // 1024}MB")

    BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{canvas_id}_{uuid.uuid4().hex[:10]}{suffix}"
    (BACKGROUND_DIR / filename).write_bytes(data)

    # 换新图，旧图删掉
    old = current.get("image") or ""
    if old and old != filename:
        try:
            _safe_background_path(old).unlink()
        except (HTTPException, OSError):
            pass

    current["image"] = filename
    _save_background(canvas_id, current)
    return {
        "ok": True,
        "filename": filename,
        "url": f"/api/backgrounds/{filename}",
        "background": current,
        "size": len(data),
    }


@router.delete("/api/canvases/{canvas_id}/background-image")
def delete_background(canvas_id: str):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        current = _row_to_background(row)
    current["image"] = ""
    _save_background(canvas_id, current)
    remove_background_files(canvas_id)
    return {"ok": True, "background": current}


def _save_background(canvas_id: str, background: Dict[str, Any]) -> None:
    model = CanvasBackground(**background).model_dump()
    with get_conn() as conn:
        conn.execute(
            "UPDATE canvases SET background = ?, updated_at = ? WHERE id = ?",
            (json.dumps(model, ensure_ascii=False), now_iso(), canvas_id),
        )
