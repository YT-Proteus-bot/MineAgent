"""生成物版本管理：列出项目的历史版本、回滚到某一版。

版本数据来自生成器写在 `projects/<slug>/` 里的三样东西：
- `VERSION`            当前版本记录（version / hash / generated_at …）
- `.history/`          最近几版 agent.py 留档（生成器每次内容变化时自动归档）
- `CHANGELOG.md`       每次版本变化的流水

这里只做「读 + 把留档拷回去」，不重新生成代码：回滚的目的就是回到当时那份代码。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .config import PROJECTS_DIR

HISTORY_KEEP = 20


def _safe_slug(slug: str) -> str:
    text = (slug or "").strip()
    if not text or "/" in text or "\\" in text or ".." in text:
        raise ValueError("非法项目名")
    return text


def project_dir(slug: str) -> Path:
    path = PROJECTS_DIR / _safe_slug(slug)
    if not path.exists():
        raise FileNotFoundError(f"项目目录不存在：{path.name}")
    return path


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def current(slug: str) -> Dict[str, Any]:
    """当前版本记录；没有 VERSION 时返回空 dict（旧项目）。"""
    return _read_json(project_dir(slug) / "VERSION")


def changelog(slug: str, limit: int = 50) -> List[str]:
    path = project_dir(slug) / "CHANGELOG.md"
    if not path.exists():
        return []
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip().startswith("- ")]
    return lines[-limit:][::-1]


def list_versions(slug: str) -> List[Dict[str, Any]]:
    """当前版本在前，其后是 .history/ 里的历史版本（新 → 旧）。"""
    root = project_dir(slug)
    now = current(slug)
    out: List[Dict[str, Any]] = []
    current_version = str(now.get("version") or "")
    if current_version:
        out.append({**now, "is_current": True,
                    "source": "agent.py"})

    history = root / ".history"
    if history.exists():
        archived = sorted(history.glob("agent-*.py"), key=lambda p: p.stat().st_mtime, reverse=True)
        seen = {current_version}
        for path in archived:
            version = path.stem.replace("agent-", "", 1)
            if version in seen:
                continue
            seen.add(version)
            meta = _read_json(history / f"VERSION-{version}.json")
            out.append({
                "version": version,
                "hash": meta.get("hash", ""),
                "generated_at": meta.get("generated_at", ""),
                "nodes": meta.get("nodes"),
                "edges": meta.get("edges"),
                "bytes": path.stat().st_size,
                "archived_at": datetime.fromtimestamp(path.stat().st_mtime)
                .astimezone().isoformat(timespec="seconds"),
                "is_current": False,
                "source": f".history/{path.name}",
            })
    return out


def rollback(slug: str, version: str) -> Dict[str, Any]:
    """把某个历史版本的文件拷回 agent.py，并把 VERSION 一并还原。"""
    root = project_dir(slug)
    version = (version or "").strip()
    if not version or "/" in version or "\\" in version or ".." in version:
        raise ValueError("非法版本号")

    target = root / ".history" / f"agent-{version}.py"
    if not target.exists():
        raise FileNotFoundError(f"没有这个版本的留档：{target.name}")

    now = current(slug)
    current_version = str(now.get("version") or "")
    if current_version == version:
        return {"changed": False, "version": version, "reason": "已经是这个版本"}

    # 回滚前把当前版本也留一档，避免「回滚后又想回去」
    if (root / "agent.py").exists() and current_version:
        backup = root / ".history" / f"agent-{current_version}.py"
        if not backup.exists():
            shutil.copyfile(root / "agent.py", backup)
        version_meta = root / ".history" / f"VERSION-{current_version}.json"
        if not version_meta.exists() and (root / "VERSION").exists():
            shutil.copyfile(root / "VERSION", version_meta)

    shutil.copyfile(target, root / "agent.py")

    restored = _read_json(root / ".history" / f"VERSION-{version}.json") or dict(now)
    restored.update({
        "version": version,
        "rolled_back_from": current_version,
        "rolled_back_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    })
    (root / "VERSION").write_text(json.dumps(restored, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")

    try:
        with (root / "CHANGELOG.md").open("a", encoding="utf-8") as fh:
            fh.write(f"- `{restored['rolled_back_at']}` **回滚到 v{version}**"
                     f"（从 v{current_version}）\n")
    except OSError:
        pass

    # 回滚后旧的 __pycache__ 会指向旧代码，清掉
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    return {"changed": True, "version": version, "rolled_back_from": current_version,
            "restored": restored}


def archive_version_meta(project_dir_path: Path, version: str) -> None:
    """生成器调用：把当前 VERSION 快照存进 .history/，回滚时才能一起还原。"""
    try:
        history = project_dir_path / ".history"
        history.mkdir(exist_ok=True)
        src = project_dir_path / "VERSION"
        if src.exists() and version:
            shutil.copyfile(src, history / f"VERSION-{version}.json")
        keep = sorted(history.glob("agent-*.py"), key=lambda p: p.stat().st_mtime)
        for stale in keep[:-HISTORY_KEEP]:
            stale.unlink(missing_ok=True)
            (history / f"VERSION-{stale.stem.replace('agent-', '', 1)}.json").unlink(missing_ok=True)
    except OSError:
        pass
