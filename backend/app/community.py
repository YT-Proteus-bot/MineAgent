"""社区模板：画布脱敏打包 + GitHub REST 客户端（只用标准库）。

说明：
- 上传永远不包含任何 API Key / token / 客户端密钥；节点模型配置里的 api_key_env
  只是环境变量名，也会一并清掉。
- OAuth 走 GitHub 授权码流程：浏览器跳转授权 → 回调换 token → 加密存本地库。
- 发布走 Pull Request：有仓库写权限就直接推分支，没有就 fork 一份再提 PR。
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .db import get_setting
from .security import decrypt

GITHUB_API = "https://api.github.com"
OAUTH_AUTHORIZE = "https://github.com/login/oauth/authorize"
OAUTH_TOKEN = "https://github.com/login/oauth/access_token"
RAW_BASE = "https://raw.githubusercontent.com"

# 这些字段名一出现就删掉，绝不带进模板
_SENSITIVE_KEYS = {
    "api_key", "apikey", "api_key_cipher", "api_key_mask", "api_key_env",
    "client_secret", "password", "private_key", "access_token", "token",
    "secret", "key_cipher",
}

# 项目目录里允许上传的文件（白名单）
_PROJECT_FILES = {
    "agent.py", "agent.json", "config.json", "README.md", "requirements.txt",
    "run.ps1", "run.sh", ".env.example", "canvas.snapshot.json",
}
_PROJECT_DIRS = {"skills"}
_MAX_FILE_BYTES = 300_000


class GitHubError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def cfg() -> Dict[str, Any]:
    return {
        "repo": get_setting("community_repo", "").strip(),
        "branch": get_setting("community_branch", "main").strip() or "main",
        "dir": (get_setting("community_dir", "templates") or "templates").strip().strip("/") or "templates",
        "client_id": get_setting("github_client_id", "").strip(),
        "connected": bool(token()),
        "login": get_setting("github_login", ""),
    }


def token() -> str:
    return decrypt(get_setting("github_token_cipher", ""))


def parse_repo(repo: str) -> Tuple[str, str]:
    parts = [p for p in (repo or "").replace(" ", "").split("/") if p]
    if len(parts) != 2:
        raise ValueError("仓库格式应为 owner/repo，例如 yourname/MineAgent-Templates")
    return parts[0], parts[1]


# --------------------------------------------------------------------------- #
# 脱敏
# --------------------------------------------------------------------------- #
def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                continue
            out[key] = _clean(val)
        return out
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def sanitize_graph(graph: Dict[str, Any]) -> Dict[str, Any]:
    """去掉所有 key/密钥字段，并清掉指向本机背景图的路径。"""
    data = _clean(graph)
    bg = data.get("background")
    if isinstance(bg, dict):
        bg["image"] = ""
    return data


def _sanitize_text(name: str, text: str) -> str:
    if name.endswith("config.json"):
        try:
            cfg_data = json.loads(text)
            cfg_data["api_key_env"] = "MINEAGENT_API_KEY"
            for bad in ("api_key", "client_secret", "token"):
                cfg_data.pop(bad, None)
            return json.dumps(cfg_data, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            return text
    return text


def collect_project_files(project_dir: Path) -> Dict[str, str]:
    """只收白名单里的项目文件，且逐个过一遍脱敏。"""
    files: Dict[str, str] = {}
    if not project_dir.is_dir():
        return files
    for name in sorted(_PROJECT_FILES):
        path = project_dir / name
        if path.is_file() and path.stat().st_size <= _MAX_FILE_BYTES:
            files[name] = _sanitize_text(name, path.read_text(encoding="utf-8", errors="replace"))
    for dirname in _PROJECT_DIRS:
        base = project_dir / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
                continue
            rel = path.relative_to(project_dir).as_posix()
            files[rel] = _sanitize_text(rel, path.read_text(encoding="utf-8", errors="replace"))
    return files


# --------------------------------------------------------------------------- #
# GitHub HTTP
# --------------------------------------------------------------------------- #
def _http(method: str, url: str, token_str: str = "", data: Any = None,
          headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> Any:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "MineAgent-Community")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token_str:
        req.add_header("Authorization", f"Bearer {token_str}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise GitHubError(f"GitHub API {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise GitHubError(f"连接 GitHub 失败：{exc.reason}") from exc


def api(method: str, path: str, token_str: str = "", data: Any = None) -> Any:
    return _http(method, GITHUB_API + path, token_str, data)


def oauth_authorize_url(base_url: str, state: str) -> str:
    conf = cfg()
    if not conf["client_id"]:
        raise ValueError("还没有配置 GitHub OAuth App 的 Client ID（用户中心 → 社区模板）")
    params = {
        "client_id": conf["client_id"],
        "redirect_uri": f"{base_url.rstrip('/')}/api/github/callback",
        "scope": "public_repo read:user",
        "state": state,
    }
    return OAUTH_AUTHORIZE + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> str:
    conf = cfg()
    secret = decrypt(get_setting("github_client_secret_cipher", ""))
    if not conf["client_id"] or not secret:
        raise ValueError("GitHub OAuth App 还没配置完整")
    data = urllib.parse.urlencode({
        "client_id": conf["client_id"],
        "client_secret": secret,
        "code": code,
    }).encode("utf-8")
    req = urllib.request.Request(OAUTH_TOKEN, data=data, method="POST")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "MineAgent-Community")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.URLError as exc:
        raise GitHubError(f"换取 GitHub token 失败：{exc.reason}") from exc
    access = payload.get("access_token", "")
    if not access:
        raise GitHubError(f"GitHub 没有返回 access_token：{payload.get('error_description') or payload}")
    return access


def github_user(token_str: str) -> Dict[str, Any]:
    return api("GET", "/user", token_str) or {}


# --------------------------------------------------------------------------- #
# 模板列表 / 内容
# --------------------------------------------------------------------------- #
def _raw_json(owner: str, repo: str, branch: str, path: str) -> Dict[str, Any]:
    url = f"{RAW_BASE}/{owner}/{repo}/{urllib.parse.quote(branch, safe='')}/{urllib.parse.quote(path, safe='/')}"
    payload = _http("GET", url, headers={"Accept": "application/json"})
    if not isinstance(payload, dict):
        raise GitHubError(f"{path} 不是合法的 JSON")
    return payload


def existing_slugs(token_str: str = "") -> set:
    conf = cfg()
    if not conf["repo"]:
        return set()
    owner, repo = parse_repo(conf["repo"])
    try:
        items = api("GET", f"/repos/{owner}/{repo}/contents/{urllib.parse.quote(conf['dir'], safe='/')}"
                           f"?ref={urllib.parse.quote(conf['branch'], safe='')}", token_str)
    except GitHubError:
        return set()
    if not isinstance(items, list):
        return set()
    return {item.get("name", "") for item in items if item.get("type") == "dir"}


def list_templates() -> List[Dict[str, Any]]:
    conf = cfg()
    if not conf["repo"]:
        return []
    owner, repo = parse_repo(conf["repo"])
    try:
        items = api("GET", f"/repos/{owner}/{repo}/contents/{urllib.parse.quote(conf['dir'], safe='/')}"
                           f"?ref={urllib.parse.quote(conf['branch'], safe='')}", token() or "")
    except GitHubError:
        return []
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in items:
        if item.get("type") != "dir":
            continue
        slug = item.get("name", "")
        try:
            meta = _raw_json(owner, repo, conf["branch"], f"{conf['dir']}/{slug}/meta.json")
        except Exception:  # noqa: BLE001
            continue
        if not meta.get("slug"):
            meta["slug"] = slug
        out.append(meta)
    out.sort(key=lambda m: str(m.get("created_at", "")), reverse=True)
    return out


def fetch_template(slug: str) -> Dict[str, Any]:
    conf = cfg()
    owner, repo = parse_repo(conf["repo"])
    safe_slug = urllib.parse.quote(slug, safe="")
    meta = _raw_json(owner, repo, conf["branch"], f"{conf['dir']}/{slug}/meta.json")
    canvas = _raw_json(owner, repo, conf["branch"], f"{conf['dir']}/{slug}/canvas.json")
    return {"meta": meta, "graph": canvas}


# --------------------------------------------------------------------------- #
# 发布 PR
# --------------------------------------------------------------------------- #
def _unique_slug(name: str, taken: set) -> str:
    from .codegen import slugify  # 局部导入，避免循环依赖

    base = slugify(name) or "template"
    slug = base
    index = 2
    while slug in taken:
        slug = f"{base}_{index}"
        index += 1
    return slug


def _pr_body(meta: Dict[str, Any], files: List[str]) -> str:
    tags = "、".join(meta.get("tags") or []) or "（无）"
    return (
        f"## 新社区模板：{meta.get('name')}\n\n"
        f"- 作者：{meta.get('author') or '匿名'}\n"
        f"- 框架：{meta.get('framework')}\n"
        f"- 节点数：{meta.get('node_count')}\n"
        f"- 标签：{tags}\n\n"
        f"{meta.get('description') or ''}\n\n"
        f"### 包含文件\n" + "\n".join(f"- `{f}`" for f in files) +
        "\n\n> 本 PR 由 MineAgent 自动创建，已剔除所有 API Key / 密钥字段。\n"
    )


def publish(canvas_row, graph: Dict[str, Any], meta: Dict[str, Any],
            project_dir: Path) -> Dict[str, Any]:
    conf = cfg()
    token_str = token()
    if not conf["repo"]:
        raise ValueError("还没有配置社区仓库（用户中心 → 社区模板）")
    if not token_str:
        raise ValueError("还没有连接 GitHub（用户中心 → 社区模板）")
    owner, repo = parse_repo(conf["repo"])
    branch = conf["branch"]

    user = github_user(token_str)
    login = user.get("login") or conf["login"] or "user"

    repo_info = api("GET", f"/repos/{owner}/{repo}", token_str)
    can_push = bool((repo_info.get("permissions") or {}).get("push"))
    target = f"{owner}/{repo}"
    head_prefix = ""
    if not can_push:
        api("POST", f"/repos/{owner}/{repo}/forks", token_str)
        for _ in range(40):
            try:
                api("GET", f"/repos/{login}/{repo}", token_str)
                break
            except GitHubError:
                time.sleep(1.5)
        target = f"{login}/{repo}"
        head_prefix = f"{login}:"

    slug = _unique_slug(meta["name"], existing_slugs(token_str))
    # 目录名就是 slug，必须写回 meta，否则社区列表里读不到（旧模板的兜底在 list_templates）
    meta["slug"] = slug
    branch_name = f"template/{slug}-{int(time.time())}"
    ref = api("GET", f"/repos/{target}/git/ref/heads/{urllib.parse.quote(branch, safe='')}", token_str)
    base_sha = (ref.get("object") or {}).get("sha")
    if not base_sha:
        raise GitHubError(f"读不到 {target} 的分支 {branch}")
    api("POST", f"/repos/{target}/git/refs", token_str,
        {"ref": f"refs/heads/{branch_name}", "sha": base_sha})

    files = collect_project_files(project_dir)
    meta["project_files"] = list(files.keys())
    tpl_dir = conf["dir"]
    payload = {
        "meta.json": json.dumps(meta, ensure_ascii=False, indent=2),
        "canvas.json": json.dumps(sanitize_graph(graph), ensure_ascii=False, indent=2),
    }
    for name, content in files.items():
        payload[f"project/{name}"] = content

    for path, content in payload.items():
        api("PUT",
            f"/repos/{target}/contents/{urllib.parse.quote(f'{tpl_dir}/{slug}/{path}', safe='/')}",
            token_str,
            {
                "message": f"feat(template): {slug} · {meta['name']}",
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch_name,
            })

    pr = api("POST", f"/repos/{owner}/{repo}/pulls", token_str, {
        "title": f"新增社区模板：{meta['name']}",
        "head": f"{head_prefix}{branch_name}",
        "base": branch,
        "body": _pr_body(meta, list(payload.keys())),
    })
    return {
        "ok": True,
        "pr_url": pr.get("html_url"),
        "pr_number": pr.get("number"),
        "branch": branch_name,
        "slug": slug,
        "files": list(payload.keys()),
    }
