"""社区模板路由：GitHub 连接、发布 PR、模板列表与加载。"""
from __future__ import annotations

import hashlib
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
        # 版本对比用：画布唯一 id、画布最后修改时间、图内容哈希
        "canvas_id": canvas_id,
        "canvas_updated_at": row["updated_at"],
        "graph_hash": community.graph_hash(graph),
        # rev 在下面冲突检测之后按"远端第几版"补上
        "rev": 0,
    }
    lib_id = str(payload.get("lib_id") or "")
    lib = community.lib_by_id(lib_id) if lib_id else None
    if lib_id and not lib:
        raise HTTPException(404, "模板库不存在")
    if not lib:
        # 没指定库：用这张画布绑定的库
        lib = community.lib_by_id(community.canvas_lib(canvas_id))
    if not lib:
        # 兜底：沿用旧的公共社区仓库配置
        conf = community.cfg()
        if not conf["repo"]:
            raise HTTPException(400, "还没有配置模板库（用户中心 → 模板库）")
        lib = {
            "id": "", "name": "社区", "kind": "public",
            "repo": conf["repo"], "branch": conf["branch"], "dir": conf["dir"],
        }
    target = "private" if lib.get("kind") == "private" else "public"
    private_conf = lib
    if target == "public":
        # 同一张画布已有未合入的 PR 时，不允许重复上传（前端也会拦，这里防直接调 API）
        try:
            pending = community.pending_prs()
        except Exception:  # noqa: BLE001
            pending = []
        blocked = any(
            (p.get("canvas_id") and p["canvas_id"] == canvas_id)
            or (not p.get("canvas_id") and p.get("name") == meta["name"])
            for p in pending
        )
        if blocked:
            raise HTTPException(409, "这张画布已有未合入的 PR，请先到 GitHub 撤销或等待合入")

    # ---- 冲突检测：本地记住的远端版本 vs 远端当前版本 ----
    # 只有「这张画布之前同步过某个模板」才需要比对；首次上传没有基线，直接走新增流程。
    base_rev = int(payload.get("base_rev") or 0)
    remote_slug = str(payload.get("remote_slug") or row["remote_slug"] or "").strip()
    remote_rev = 0
    # force=True 表示用户在冲突对话框里明确选了"仍然覆盖"
    force = bool(payload.get("force"))
    if remote_slug and base_rev > 0 and not force:
        remote_meta: Dict[str, Any] = {}
        try:
            remote_meta = community.fetch_meta(remote_slug, conf=private_conf)
        except Exception:  # noqa: BLE001  远端读不到就当作模板还不存在
            remote_meta = {}
        remote_rev = int(remote_meta.get("rev") or 0)
        if remote_rev and remote_rev != base_rev:
            raise HTTPException(409, {
                "kind": "remote-changed",
                "message": (f"远端模板在你上次同步之后又更新了"
                            f"（你的是第 {base_rev} 版，远端现在是第 {remote_rev} 版）"),
                "remote_slug": remote_slug,
                "base_rev": base_rev,
                "remote_rev": remote_rev,
                "remote_updated_at": remote_meta.get("updated_at", ""),
                "remote_author": remote_meta.get("author", ""),
            })

    # 版本号：更新已有模板就 +1，首次上传从 1 开始
    meta["rev"] = (remote_rev + 1) if (remote_slug and remote_rev) else 1
    meta["updated_at"] = now_iso()

    try:
        result = community.publish(
            row, graph, meta, project_dir,
            target=target, conf_override=private_conf,
            slug_override=remote_slug if (remote_slug and (base_rev > 0 or force)) else "",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except community.GitHubError as exc:
        raise HTTPException(502, str(exc)) from exc

    # 推送成功后记住这次同步的版本，下次才能判断"远端有没有被别人改过"
    applied_slug = str(result.get("slug") or meta.get("slug") or "").strip()
    next_rev = int(meta.get("rev") or 0) or ((int(remote_rev) + 1) if remote_slug else 1)
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE canvases SET remote_slug = ?, remote_rev = ?, base_graph_hash = ?, "
                "remote_lib = ?, remote_name = ? WHERE id = ?",
                (applied_slug, next_rev, community.graph_hash(graph),
                 ("private:" + str(private_conf.get("repo", ""))) if target == "private" else "public",
                 str(meta.get("name") or applied_slug), canvas_id),
            )
    except Exception:  # noqa: BLE001  记忆失败不影响本次推送结果
        pass
    result["rev"] = next_rev
    result["remote_slug"] = applied_slug
    return result


@router.get("/templates")
def templates():
    conf = community.cfg()
    if not conf["repo"]:
        return {"ok": True, "configured": False, "templates": []}
    return {"ok": True, "configured": True, "templates": community.list_templates()}


@router.get("/pending")
def pending():
    """已上传、PR 还没合入的模板名（上传弹窗里标「已上传待合入」）。"""
    conf = community.cfg()
    if not conf["repo"]:
        return {"ok": True, "pending": []}
    return {"ok": True, "pending": community.pending_prs()}


@router.get("/canvas-status")
def canvas_status():
    """公共模板元信息 + 全部 PR 状态，给上传弹窗做版本对比和 PR 状态展示。"""
    conf = community.cfg()
    if not conf["repo"]:
        return {"ok": True, "templates": [], "prs": []}
    data = community.canvas_status()
    return {"ok": True, **data}


def _install_template(data: Dict[str, Any], lib: str = "public") -> Dict[str, Any]:
    """把模板（meta + graph）安装成一张新画布。公共/私人模板共用。"""
    meta = data["meta"]
    try:
        graph = Graph(**data["graph"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"模板画布格式不合法：{exc}") from exc
    graph_dict = graph.model_dump()
    graph_dict["background"] = CanvasBackground().model_dump()

    name = str(meta.get("name") or meta.get("slug") or "模板").strip() or "模板"
    framework = str(meta.get("framework") or "langchain")
    canvas_id = uuid.uuid4().hex
    remote_slug = str(meta.get("slug") or "")
    remote_rev = int(meta.get("rev") or 1)
    remote_name = str(meta.get("name") or remote_slug)
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
            "remote_slug,remote_rev,base_graph_hash,remote_lib,remote_name,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (canvas_id, display, final_slug, framework,
             json.dumps(graph_dict, ensure_ascii=False),
             json.dumps(default_model, ensure_ascii=False),
             json.dumps(graph_dict["background"], ensure_ascii=False),
             str(meta.get("mode") or ""), ts, ts,
             remote_slug, remote_rev, community.graph_hash(graph_dict), lib, remote_name),
        )
        try:
            _persist(conn, canvas_id, graph_dict, touch=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"生成项目代码失败：{exc}") from exc
        row = _fetch(conn, canvas_id)
    return {"ok": True, "canvas": _detail(row)}


def _private_conf(canvas_id: str) -> Dict[str, Any]:
    conf = community.private_settings(canvas_id)
    if not conf["repo"]:
        raise HTTPException(400, "这张画布还没有配置私人模板库")
    return conf


@router.get("/libs")
def list_libs():
    """用户中心配置的所有模板库（公共 / 私人，可多个）。"""
    return {"ok": True, "libs": community.template_libs()}


@router.put("/libs")
def save_libs(payload: Dict[str, Any]):
    """保存模板库前逐个校验：重复的、GitHub 上找不到的都不保存，并一次列出所有问题。"""
    items = payload.get("libs") or []
    if not community.token():
        raise HTTPException(400, "还没有连接 GitHub，无法校验仓库")
    checked: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    errors: List[str] = []
    for index, item in enumerate(items, start=1):
        repo = str(item.get("repo") or "").strip()
        label = str(item.get("name") or "").strip() or f"第 {index} 个仓库"
        if not repo:
            errors.append(f"「{label}」的仓库地址必填")
            continue
        try:
            owner_name, repo_name = community.parse_repo(repo)
        except ValueError as exc:
            errors.append(f"「{label}」格式不对：{exc}")
            continue
        target = f"{owner_name}/{repo_name}"
        if target.lower() in seen:
            errors.append(f"「{label}」重复添加：{target} 和第 {seen[target.lower()]} 个仓库是同一个")
            continue
        seen[target.lower()] = index
        try:
            info = community.repo_info(target)
        except community.GitHubError as exc:
            scopes = community.token_scopes()
            if "repo" not in scopes:
                errors.append(
                    f"「{label}」在 GitHub 上找不到或无权访问：{target}"
                    f"（当前授权只有 {', '.join(sorted(scopes)) or '未知'}，"
                    f"读私有仓库需要 repo 权限，请到用户中心 → GitHub 账户断开后重新连接）"
                )
            else:
                errors.append(f"「{label}」在 GitHub 上找不到或无权访问：{target}")
            continue
        except ValueError as exc:
            errors.append(f"「{label}」校验失败：{exc}")
            continue
        branch = str(item.get("branch") or "main").strip() or "main"
        dir_path = str(item.get("dir") or "templates").strip().strip("/") or "templates"
        if not community.dir_exists(target, branch, dir_path):
            errors.append(
                f"「{label}」的目录 {dir_path} 在分支 {branch} 下不存在"
                f"（检查目录名，或先在仓库里创建它）"
            )
            continue
        checked.append({
            **item,
            "repo": target,
            "visibility": "private" if info.get("private") else "public",
        })
    if errors:
        raise HTTPException(400, "没有保存，以下模板库不符合要求：" + "；".join(errors))
    try:
        libs = community.save_template_libs(checked)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "libs": libs}


@router.get("/canvas-lib")
def read_canvas_lib(canvas_id: str):
    return {"ok": True, "lib_id": community.canvas_lib(canvas_id)}


@router.put("/canvas-lib")
def write_canvas_lib(payload: Dict[str, Any]):
    canvas_id = str(payload.get("canvas_id") or "")
    lib_id = str(payload.get("lib_id") or "")
    if not canvas_id:
        raise HTTPException(400, "缺少 canvas_id")
    if lib_id and not community.lib_by_id(lib_id):
        raise HTTPException(400, "模板库不存在")
    return {"ok": True, "lib_id": community.save_canvas_lib(canvas_id, lib_id)}


@router.get("/lib-count")
def lib_count(lib_id: str):
    """模板数量：只列目录，一次请求，不读 meta。"""
    lib = community.lib_by_id(lib_id)
    if not lib:
        raise HTTPException(404, "模板库不存在")
    return {"ok": True, "count": community.template_count(lib)}


@router.get("/lib-templates")
def lib_templates(lib_id: str, refresh: bool = False):
    lib = community.lib_by_id(lib_id)
    if not lib:
        raise HTTPException(404, "模板库不存在")
    return {"ok": True, "lib": lib, "templates": community.list_templates(lib, force=refresh)}


@router.post("/lib-load")
def lib_load(payload: Dict[str, Any]):
    lib_id = str(payload.get("lib_id") or "")
    slug = str(payload.get("slug") or "").strip()
    lib = community.lib_by_id(lib_id)
    if not lib:
        raise HTTPException(404, "模板库不存在")
    if not slug:
        raise HTTPException(400, "缺少模板 slug")
    try:
        data = community.fetch_template(slug, lib)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except community.GitHubError as exc:
        raise HTTPException(502, f"下载模板失败：{exc}") from exc
    return _install_template(data)


@router.get("/private-config")
def read_private_config(canvas_id: str):
    return {"ok": True, **community.private_settings(canvas_id)}


@router.put("/private-config")
def write_private_config(payload: Dict[str, Any]):
    canvas_id = str(payload.get("canvas_id") or "")
    if not canvas_id:
        raise HTTPException(400, "缺少 canvas_id")
    try:
        conf = community.save_private_settings(canvas_id, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **conf}


@router.get("/private-templates")
def private_templates(canvas_id: str):
    conf = _private_conf(canvas_id)
    return {"ok": True, "templates": community.list_templates(conf)}


@router.post("/private-load")
def private_load(payload: Dict[str, Any]):
    canvas_id = str(payload.get("canvas_id") or "")
    slug = str(payload.get("slug") or "").strip()
    if not canvas_id or not slug:
        raise HTTPException(400, "缺少 canvas_id 或 slug")
    conf = _private_conf(canvas_id)
    try:
        data = community.fetch_template(slug, conf)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except community.GitHubError as exc:
        raise HTTPException(502, f"下载模板失败：{exc}") from exc
    return _install_template(data, lib=f"private:{conf.get('repo', '')}")


@router.post("/load")
def load_template(payload: Dict[str, Any]):
    """加载社区模板。

    mode=new（默认）：新建一张画布
    mode=update：用远端内容更新已有画布，会先检查本地有没有未同步的改动
    """
    slug = str(payload.get("slug") or "").strip()
    if not slug:
        raise HTTPException(400, "缺少模板 slug")
    mode = str(payload.get("mode") or "new").lower()
    if mode == "update":
        return _update_from_template(slug, payload)
    try:
        data = community.fetch_template(slug)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except community.GitHubError as exc:
        raise HTTPException(502, f"下载模板失败：{exc}") from exc
    return _install_template(data)


def _update_from_template(slug: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """用远端模板覆盖已有画布。本地有未同步改动时，除非显式 force，否则拒绝。"""
    canvas_id = str(payload.get("canvas_id") or "").strip()
    if not canvas_id:
        raise HTTPException(400, "更新模式需要 canvas_id")
    force = bool(payload.get("force"))

    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
    local_graph = json.loads(row["graph"] or "{}")
    base_hash = str(row["base_graph_hash"] or "")
    local_hash = community.graph_hash(local_graph)
    local_changed = bool(base_hash) and local_hash != base_hash

    if local_changed and not force:
        raise HTTPException(409, {
            "kind": "local-changed",
            "message": "本地这张画布有还没同步到远端的修改，直接覆盖会丢掉它们",
            "canvas_id": canvas_id,
            "canvas_name": row["name"],
            "remote_slug": slug,
            "local_rev": int(row["remote_rev"] or 0),
            "base_hash": base_hash,
            "local_hash": local_hash,
        })

    try:
        data = community.fetch_template(slug)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except community.GitHubError as exc:
        raise HTTPException(502, f"下载模板失败：{exc}") from exc

    meta = data.get("meta") or {}
    try:
        graph = Graph(**data["graph"]).model_dump()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"模板画布格式不合法：{exc}") from exc
    graph["background"] = row["background"] and json.loads(
        row["background"] or "{}") or CanvasBackground().model_dump()

    remote_rev = int(meta.get("rev") or 1)
    with get_conn() as conn:
        conn.execute(
            "UPDATE canvases SET graph = ?, framework = ?, mode = ?, name = ?, updated_at = ? "
            "WHERE id = ?",
            (json.dumps(graph, ensure_ascii=False), str(meta.get("framework") or row["framework"]),
             str(meta.get("mode") or row["mode"] or ""),
             str(meta.get("name") or row["name"]), now_iso(), canvas_id),
        )
        try:
            _persist(conn, canvas_id, graph)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"生成项目代码失败：{exc}") from exc
        conn.execute(
            "UPDATE canvases SET remote_slug = ?, remote_rev = ?, base_graph_hash = ?, "
            "remote_lib = ?, remote_name = ? WHERE id = ?",
            (slug, remote_rev, community.graph_hash(graph),
             str(row["remote_lib"] or "public"), str(meta.get("name") or slug), canvas_id),
        )
        updated = _fetch(conn, canvas_id)
    return {"ok": True, "mode": "update", "rev": remote_rev, "canvas": _detail(updated)}


def _lib_label(lib: str) -> str:
    """把库标识转成能直接显示的名字。

    public              → 公共模板库
    private:owner/repo  → 私人库 owner/repo
    """
    lib = (lib or "").strip()
    if lib.startswith("private:"):
        repo = lib.split(":", 1)[1].strip()
        return f"私人库 {repo}" if repo else "私人库"
    return "公共模板库"


@router.get("/sync-overview")
def sync_overview():
    """把所有绑定了远端的画布，连同"远端有没有新版"一次性算出来。

    按库分组只拉一次模板列表，避免每个画布一次 GitHub 请求。
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, remote_slug, remote_rev, remote_lib, base_graph_hash, graph "
            "FROM canvases WHERE remote_slug != ''"
        ).fetchall()
    if not rows:
        return {"ok": True, "items": []}

    cache: Dict[str, Dict[str, Any]] = {}

    def templates_of(lib: str, canvas_id: str) -> Dict[str, Any]:
        if lib in cache:
            return cache[lib]
        try:
            if lib.startswith("private:"):
                conf = community.private_settings(canvas_id)
                repo = lib.split(":", 1)[1]
                if repo:
                    conf = {**conf, "repo": repo}
                items = community.list_templates(conf) if conf.get("repo") else []
            else:
                items = community.list_templates(community.cfg())
            cache[lib] = {str(t.get("slug") or ""): t for t in items}
        except Exception:  # noqa: BLE001  某个库读不到不影响其它画布
            cache[lib] = {}
        return cache[lib]

    out: List[Dict[str, Any]] = []
    for row in rows:
        slug = str(row["remote_slug"] or "")
        lib = str(row["remote_lib"] or "public")
        local_rev = int(row["remote_rev"] or 0)
        meta = templates_of(lib, row["id"]).get(slug) or {}
        remote_rev = int(meta.get("rev") or 0)

        graph = json.loads(row["graph"] or "{}")
        base_hash = str(row["base_graph_hash"] or "")
        local_changed = bool(base_hash) and community.graph_hash(graph) != base_hash

        out.append({
            "canvas_id": row["id"],
            "canvas_name": row["name"],
            "remote_slug": slug,
            "remote_lib": lib,
            # 可读的库名：不管这张画布是拉下来的还是本地原创推上去的，都指向同一个远端库
            "remote_lib_label": _lib_label(lib),
            "remote_name": str(meta.get("name") or slug),
            "local_rev": local_rev,
            "remote_rev": remote_rev,
            # 远端读不到时 remote_rev=0，按"没有更新"处理，不打扰用户
            "remote_changed": bool(remote_rev and remote_rev > local_rev),
            "local_changed": local_changed,
            "remote_updated_at": meta.get("updated_at", ""),
        })

    # 顺手把模板名写回画布表，画布下拉里直接能显示，不用每次再查
    try:
        with get_conn() as conn:
            for item in out:
                conn.execute(
                    "UPDATE canvases SET remote_name = ? WHERE id = ?",
                    (item["remote_name"], item["canvas_id"]),
                )
    except Exception:  # noqa: BLE001  兼容还没这一列的老库
        pass

    return {"ok": True, "items": out}


@router.get("/sync-status/{canvas_id}")
def sync_status(canvas_id: str):
    """本地画布和它绑定的远端模板，各自有没有新变化。"""
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
    graph = json.loads(row["graph"] or "{}")
    local_hash = community.graph_hash(graph)
    remote_slug = str(row["remote_slug"] or "")

    if not remote_slug:
        return {"ok": True, "linked": False,
                "local_changed": False, "remote_changed": False}

    # 本地有没有改动只看本地数据，不依赖网络；远端读不到时也要告诉用户本地状态
    base_hash = str(row["base_graph_hash"] or "")
    local_changed = bool(base_hash) and local_hash != base_hash
    local_rev = int(row["remote_rev"] or 0)

    try:
        meta = community.fetch_meta(remote_slug)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False, "linked": True, "remote_slug": remote_slug,
            "local_changed": local_changed, "remote_changed": False,
            "local_rev": local_rev, "local_hash": local_hash,
            "error": f"读不到远端模板：{exc}",
        }

    remote_rev = int(meta.get("rev") or 1)
    return {
        "ok": True,
        "linked": True,
        "remote_slug": remote_slug,
        "local_rev": local_rev,
        "remote_rev": remote_rev,
        "local_changed": local_changed,
        "remote_changed": remote_rev > local_rev,
        "local_hash": local_hash,
        "remote_hash": str(meta.get("graph_hash") or ""),
        "remote_updated_at": meta.get("updated_at", ""),
    }
