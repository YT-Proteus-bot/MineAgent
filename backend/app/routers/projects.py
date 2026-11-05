"""生成项目的文件浏览与手动编辑。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException

from ..config import PROJECTS_DIR
from ..db import get_conn
from ..schemas import ProjectFile
from .canvases import _fetch

router = APIRouter(prefix="/api/canvases", tags=["project"])

TEXT_EXT = {".py", ".md", ".json", ".txt", ".yaml", ".yml", ".toml", ".env", ".example", ""}
LANG = {".py": "python", ".md": "markdown", ".json": "json", ".txt": "text",
        ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".example": "text"}


def _project_dir(canvas_id: str) -> Path:
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
    path = (PROJECTS_DIR / row["slug"]).resolve()
    if PROJECTS_DIR.resolve() not in path.parents:
        raise HTTPException(400, "非法项目路径")
    return path


@router.get("/{canvas_id}/files")
def list_files(canvas_id: str):
    root = _project_dir(canvas_id)
    if not root.exists():
        return {"root": str(root), "files": []}
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        if "__pycache__" in rel or rel.startswith(".store"):
            continue
        files.append({"path": rel, "size": path.stat().st_size,
                      "language": LANG.get(path.suffix.lower(), "text")})
    return {"root": str(root), "files": files}


@router.get("/{canvas_id}/file")
def read_file(canvas_id: str, path: str):
    root = _project_dir(canvas_id)
    target = (root / path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(400, "越界路径")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")
    if target.suffix.lower() not in TEXT_EXT:
        raise HTTPException(400, "不支持的文件类型")
    return ProjectFile(path=path, content=target.read_text(encoding="utf-8", errors="replace"),
                       language=LANG.get(target.suffix.lower(), "text"))


@router.put("/{canvas_id}/file")
def write_file(canvas_id: str, payload: ProjectFile):
    root = _project_dir(canvas_id)
    target = (root / payload.path).resolve()
    if root not in target.parents:
        raise HTTPException(400, "越界路径")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload.content, encoding="utf-8", newline="\n")
    return {"ok": True, "path": payload.path}


@router.post("/{canvas_id}/open-folder")
def open_folder(canvas_id: str):
    root = _project_dir(canvas_id)
    root.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(root)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(root)])
        else:
            subprocess.Popen(["xdg-open", str(root)])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"打开目录失败：{exc}") from exc
    return {"ok": True, "path": str(root)}
