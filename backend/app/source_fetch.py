"""把三种来源统一成「一个本地目录」，供 source_scan 扫描。

- github：下载仓库 zipball 后解压（不依赖本机装 git）
- upload：用户上传的 zip / tar.gz
- local ：本地已有目录

安全约束：解压时拒绝绝对路径和 .. 穿越；本地路径拒绝系统目录。
"""
from __future__ import annotations

import io
import json
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

from .config import DATA_DIR

SOURCES_DIR = DATA_DIR / "sources"
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_EXTRACT_FILES = 5000

# 本地路径不允许指到这些地方（防止让 AI 去翻系统目录）
DENY_PREFIXES = (
    "c:\\windows", "c:\\program files", "c:\\program files (x86)",
    "/etc", "/usr", "/bin", "/sbin", "/var", "/proc", "/sys", "/dev",
)


class SourceError(ValueError):
    pass


def _root_dir(source_id: str) -> Path:
    return SOURCES_DIR / source_id


def _save_meta(source_id: str, meta: Dict[str, Any]) -> None:
    path = _root_dir(source_id) / "meta.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def load_meta(source_id: str) -> Optional[Dict[str, Any]]:
    path = _root_dir(source_id) / "meta.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def code_dir(source_id: str) -> Path:
    """源码实际所在目录（解压时可能有一层顶层目录，已提升）。"""
    root = _root_dir(source_id)
    meta = load_meta(source_id) or {}
    rel = meta.get("code_dir") or "src"
    return root / rel


def _safe_member(name: str) -> bool:
    normalized = name.replace("\\", "/").lstrip("/")
    if normalized.startswith("../") or "/../" in normalized:
        return False
    if re.match(r"^[a-zA-Z]:", name):
        return False
    return True


def _extract_zip(data: bytes, target: Path) -> int:
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.infolist():
            if member.is_dir() or not _safe_member(member.filename):
                continue
            if count >= MAX_EXTRACT_FILES:
                break
            out = target / member.filename
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count


def _extract_tar(data: bytes, target: Path) -> int:
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        for member in tf.getmembers():
            if not member.isfile() or not _safe_member(member.name):
                continue
            if count >= MAX_EXTRACT_FILES:
                break
            out = target / member.name
            out.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            with src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count


def _flatten_if_single(target: Path) -> str:
    """zipball / 很多压缩包外面有一层目录，这里把它提上来。"""
    entries = [e for e in target.iterdir() if e.name != "meta.json"] \
        if target.exists() else []
    dirs = [e for e in entries if e.is_dir()]
    files = [e for e in entries if e.is_file()]
    if len(dirs) == 1 and not files:
        inner = dirs[0]
        moved = target.parent / f"{target.name}__flat"
        shutil.move(str(inner), str(moved))
        inner.rmdir() if inner.exists() else None
        for child in list(target.iterdir()):
            if child.name != "meta.json":
                shutil.move(str(child), str(moved / child.name))
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(moved), str(target))
    return "src"


def _new_source(kind: str, label: str, extra: Optional[Dict[str, Any]] = None) -> str:
    source_id = uuid.uuid4().hex[:16]
    root = _root_dir(source_id)
    (root / "src").mkdir(parents=True, exist_ok=True)
    meta = {"id": source_id, "kind": kind, "label": label,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "code_dir": "src"}
    meta.update(extra or {})
    _save_meta(source_id, meta)
    return source_id


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #
GITHUB_RE = re.compile(
    r"(?:github\.com[:/])(?P<owner>[\w.\-]+)/(?P<repo>[\w.\-]+?)(?:\.git)?"
    r"(?:/(?:tree|blob)/(?P<ref>[^/?#]+))?/*$", re.IGNORECASE)


def parse_github(url: str) -> Dict[str, str]:
    text = (url or "").strip()
    match = GITHUB_RE.search(text)
    if not match:
        raise SourceError(f"看起来不是 GitHub 仓库地址：{url}")
    return {"owner": match.group("owner"), "repo": match.group("repo"),
            "ref": match.group("ref") or ""}


def _github_token() -> str:
    """复用「用户中心 → 社区模板」那套 GitHub 授权。

    带上它就能读账号有权限的私有仓库；没连过就是空串，只能读公开仓库。
    """
    try:
        from . import community
        return (community.token() or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def from_github(url: str) -> str:
    info = parse_github(url)
    token = _github_token()
    source_id = _new_source("github", f"{info['owner']}/{info['repo']}",
                            {"url": url, "private": bool(token), **info})
    target = _root_dir(source_id) / "src"
    ref = info["ref"] or "HEAD"
    # 私有仓库只有 API 那条路认 token，codeload 是公开仓库的快捷通道
    candidates = [
        f"https://api.github.com/repos/{info['owner']}/{info['repo']}/zipball/{ref}",
        f"https://codeload.github.com/{info['owner']}/{info['repo']}/zip/{ref}",
    ]
    last = ""
    last_status = 0
    for candidate in candidates:
        try:
            headers = {
                "User-Agent": "MineAgent-SourceScan",
                "Accept": "application/vnd.github+json",
            }
            if token:
                headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(candidate, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
            if len(data) > MAX_ARCHIVE_BYTES:
                raise SourceError(f"仓库包太大（{len(data) // 1024 // 1024}MB）")
            count = _extract_zip(data, target)
            _flatten_if_single(target)
            meta = load_meta(source_id) or {}
            meta["files"] = count
            meta["download_from"] = candidate
            meta["private"] = bool(token) and "api.github.com" in candidate
            _save_meta(source_id, meta)
            return source_id
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            last = f"HTTP {exc.code}"
            shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
        except (urllib.error.URLError, OSError, zipfile.BadZipFile) as exc:
            last = str(exc)[:200]
            shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)

    if last_status == 404:
        if token:
            scopes: set = set()
            try:
                from . import community
                scopes = community.token_scopes()
            except Exception:  # noqa: BLE001
                scopes = set()
            if scopes and "repo" not in scopes:
                raise SourceError(
                    f"读不到 {info['owner']}/{info['repo']}：可能是私有仓库，"
                    "也可能仓库名不对。当前 GitHub 授权范围是 "
                    f"{'/'.join(sorted(scopes))}，只能读公开仓库——"
                    "要读私有仓库，去「用户中心 → 社区模板」先断开再重新连接，"
                    "授权页勾上 repo 权限")
            raise SourceError(
                f"读不到 {info['owner']}/{info['repo']}：仓库不存在，"
                "或者你当前授权的 GitHub 账号没有这个仓库的访问权")
        raise SourceError(
            f"读不到 {info['owner']}/{info['repo']}：仓库不存在，"
            "或者它是私有仓库。私有仓库请先去「用户中心 → 社区模板」连接 GitHub 账号")
    if last_status in (401, 403):
        raise SourceError(
            "GitHub 授权无效或没有仓库读取权限：去「用户中心 → 社区模板」重新连接，"
            "并确认授权范围包含 repo")
    raise SourceError(f"下载仓库失败：{last}")


# --------------------------------------------------------------------------- #
# 上传
# --------------------------------------------------------------------------- #
def from_upload(filename: str, data: bytes) -> str:
    if not data:
        raise SourceError("压缩包是空的")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise SourceError(f"压缩包超过 {MAX_ARCHIVE_BYTES // 1024 // 1024}MB")
    name = (filename or "upload.zip").lower()
    source_id = _new_source("upload", filename or "upload")
    target = _root_dir(source_id) / "src"
    try:
        if name.endswith((".zip",)):
            count = _extract_zip(data, target)
        elif name.endswith((".tar.gz", ".tgz", ".tar", ".tar.bz2", ".tar.xz")):
            count = _extract_tar(data, target)
        else:
            raise SourceError("只支持 .zip / .tar.gz / .tgz / .tar")
    except (zipfile.BadZipFile, tarfile.TarError) as exc:
        raise SourceError(f"压缩包解析失败：{exc}") from exc
    if count == 0:
        raise SourceError("压缩包里没有可读文件")
    _flatten_if_single(target)
    meta = load_meta(source_id) or {}
    meta["files"] = count
    _save_meta(source_id, meta)
    return source_id


# --------------------------------------------------------------------------- #
# 本地目录
# --------------------------------------------------------------------------- #
def from_local(path_str: str) -> str:
    raw = (path_str or "").strip().strip('"').strip("'")
    if not raw:
        raise SourceError("本地路径为空")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    lowered = str(path).lower().replace("/", "\\")
    if any(lowered.startswith(prefix) for prefix in DENY_PREFIXES):
        raise SourceError(f"不允许读取系统目录：{path}")
    if not path.exists():
        raise SourceError(f"路径不存在：{path}")
    if not path.is_dir():
        raise SourceError(f"不是目录：{path}")
    source_id = _new_source("local", path.name, {"path": str(path)})
    target = _root_dir(source_id) / "src"
    # 本地目录不复制，记录后端能直接读的实际路径（复制大仓太慢）
    shutil.rmtree(target, ignore_errors=True)
    meta = load_meta(source_id) or {}
    meta["code_dir"] = ""
    meta["abs_path"] = str(path)
    _save_meta(source_id, meta)
    return source_id


def resolve_dir(source_id: str) -> Path:
    meta = load_meta(source_id)
    if meta is None:
        raise SourceError(f"源码包不存在：{source_id}")
    if meta.get("abs_path"):
        return Path(meta["abs_path"])
    return code_dir(source_id)


def list_sources() -> list:
    if not SOURCES_DIR.exists():
        return []
    out = []
    for entry in sorted(SOURCES_DIR.iterdir(), key=lambda p: p.name, reverse=True):
        if not entry.is_dir():
            continue
        meta = load_meta(entry.name)
        if meta:
            out.append(meta)
    return out[:50]


def remove_source(source_id: str) -> bool:
    root = _root_dir(source_id)
    if not root.exists():
        return False
    shutil.rmtree(root, ignore_errors=True)
    return True
