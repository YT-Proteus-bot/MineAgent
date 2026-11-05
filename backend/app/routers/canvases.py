"""画布 CRUD + 保存落盘。"""
from __future__ import annotations

import json
import re
import shutil
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from ..codegen import generate_project, unique_slug
from ..config import BACKGROUND_DIR, PROJECTS_DIR
from ..constraints import validate as validate_graph
from ..db import get_conn, get_setting, now_iso, set_setting
from ..framework_templates import FRAMEWORK_INDEX, build_graph
from ..schemas import (AgentNodeModel, CanvasBackground, CanvasCreate, CanvasDetail,
                       CanvasSummary, CanvasUpdate, ConstraintReport, GlobalSettings, Graph,
                       ModelConfig, SaveResult)
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


def _row_to_background(row) -> Dict[str, Any]:
    try:
        raw = json.loads(row["background"] or "{}")
    except Exception:
        raw = {}
    base = CanvasBackground().model_dump()
    base.update({k: v for k, v in raw.items() if k in base})
    return base


def _row_to_rules(row) -> List[Dict[str, Any]]:
    try:
        raw = json.loads(row["rules"] or "[]")
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _node_key_env(node_id: str) -> str:
    """节点级 api key 的环境变量名（运行时注入，不落盘）。"""
    safe = re.sub(r"[^A-Za-z0-9]", "_", node_id or "").upper()[:40]
    return f"MINEAGENT_KEY_{safe or 'NODE'}"


def load_node_models(canvas_id: str) -> Dict[str, Dict[str, Any]]:
    """读这个画布所有节点级模型配置（key 只回显掩码）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT node_id, config, api_key_cipher FROM agent_models WHERE canvas_id = ?",
            (canvas_id,),
        ).fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        try:
            cfg = json.loads(row["config"] or "{}")
        except Exception:
            cfg = {}
        key = decrypt(row["api_key_cipher"]) if row["api_key_cipher"] else ""
        cfg["api_key_env"] = _node_key_env(row["node_id"])
        cfg["api_key_mask"] = mask(key) if key else ""
        cfg["has_key"] = bool(key)
        out[row["node_id"]] = cfg
    return out


def _summary(row) -> CanvasSummary:
    graph = json.loads(row["graph"] or "{}")
    return CanvasSummary(
        id=row["id"], name=row["name"], slug=row["slug"], framework=row["framework"],
        node_count=len(graph.get("nodes", [])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _detail(row) -> CanvasDetail:
    graph = json.loads(row["graph"] or "{}")
    models = load_node_models(row["id"])
    if models:
        for node in graph.get("nodes", []):
            cfg = models.get(node.get("id"))
            if cfg:
                node.setdefault("data", {})["model"] = cfg
    return CanvasDetail(
        **_summary(row).model_dump(),
        graph=Graph(**graph),
        llm_config=ModelConfig(**_row_to_config(row)),
        background=CanvasBackground(**_row_to_background(row)),
        rules=_row_to_rules(row),
        mode=(row["mode"] if "mode" in row.keys() else "") or "",
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
    graph["background"] = CanvasBackground().model_dump()
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
            "INSERT INTO canvases(id,name,slug,framework,graph,model_config,background,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (canvas_id, name, slug, framework, json.dumps(graph, ensure_ascii=False),
             json.dumps(default_model, ensure_ascii=False),
             json.dumps(graph["background"], ensure_ascii=False), ts, ts),
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

        if payload.background is not None:
            fields["background"] = json.dumps(payload.background.model_dump(), ensure_ascii=False)

        if payload.rules is not None:
            fields["rules"] = json.dumps(payload.rules, ensure_ascii=False)

        if payload.mode is not None:
            fields["mode"] = payload.mode.strip()

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
def save_canvas_endpoint(canvas_id: str, graph: Graph, force: bool = False):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        rules = _row_to_rules(row)
        graph_dict = graph.model_dump()
        # 保存不拦人（可能只是编辑中间态），但把违规项一并返回，前端据此提示
        report = validate_graph(graph_dict, rules)
        # 先生成代码：过程中会把每个节点在 agent.py 里的代码块写回 graph_dict，
        # 所以必须再落库，否则网页上看到的还是旧代码
        try:
            result = _persist(conn, canvas_id, graph_dict, touch=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"落盘失败：{exc}") from exc
        conn.execute(
            "UPDATE canvases SET graph = ?, background = ?, updated_at = ? WHERE id = ?",
            (json.dumps(graph_dict, ensure_ascii=False),
             json.dumps(graph.background.model_dump(), ensure_ascii=False),
             now_iso(), canvas_id),
        )
        row = _fetch(conn, canvas_id)
    return SaveResult(ok=True, canvas=_detail(row),
                      project_dir=result["project_dir"], written_files=result["files"],
                      constraints=ConstraintReport(**report))


@router.post("/{canvas_id}/validate", response_model=ConstraintReport)
def validate_canvas(canvas_id: str, graph: Optional[Graph] = None):
    """校验当前画布。

    传 graph 就校验这份（用于边编辑边检查，不用先保存）；
    不传或传空图则校验数据库里已保存的那份。
    """
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        rules = _row_to_rules(row)
    if graph is not None and (graph.nodes or graph.edges):
        target = graph.model_dump()
    else:
        target = json.loads(row["graph"] or "{}")
    return ConstraintReport(**validate_graph(target, rules))


@router.put("/{canvas_id}/rules")
def set_canvas_rules(canvas_id: str, rules: List[Dict[str, Any]]):
    with get_conn() as conn:
        _fetch(conn, canvas_id)
        conn.execute("UPDATE canvases SET rules = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(rules, ensure_ascii=False), now_iso(), canvas_id))
    return {"ok": True, "rules": rules}


@router.put("/{canvas_id}/nodes/{node_id}/model")
def set_node_model(canvas_id: str, node_id: str, payload: AgentNodeModel):
    """给单个 agent 节点配置模型与 key（key 加密入库，永不进画布 JSON）。"""
    with get_conn() as conn:
        _fetch(conn, canvas_id)
        existing = conn.execute(
            "SELECT * FROM agent_models WHERE canvas_id = ? AND node_id = ?",
            (canvas_id, node_id),
        ).fetchone()
        cipher = existing["api_key_cipher"] if existing else ""
        cfg = payload.model_dump()
        api_key = cfg.pop("api_key", None)
        cfg.pop("api_key_mask", None)
        cfg.pop("has_key", None)
        cfg["api_key_env"] = _node_key_env(node_id)
        if api_key is not None:
            cipher = encrypt(api_key.strip()) if api_key.strip() else ""
        conn.execute(
            "INSERT INTO agent_models(canvas_id,node_id,config,api_key_cipher,updated_at)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(canvas_id,node_id) DO UPDATE SET"
            " config=excluded.config, api_key_cipher=excluded.api_key_cipher,"
            " updated_at=excluded.updated_at",
            (canvas_id, node_id, json.dumps(cfg, ensure_ascii=False), cipher, now_iso()),
        )
        # 同时把"非密钥部分"写回画布图，这样保存时生成 agent.py 能拿到节点级模型
        _sync_node_model_into_graph(conn, canvas_id, node_id, cfg)
    key = decrypt(cipher) if cipher else ""
    return {**cfg, "api_key_mask": mask(key) if key else "", "has_key": bool(key)}


def _sync_node_model_into_graph(conn, canvas_id: str, node_id: str,
                                cfg: Dict[str, Any] | None) -> None:
    """把节点级模型配置写进 canvases.graph 里对应节点的 data.model。"""
    row = conn.execute("SELECT graph FROM canvases WHERE id = ?", (canvas_id,)).fetchone()
    if not row:
        return
    try:
        graph = json.loads(row["graph"] or "{}")
    except Exception:  # noqa: BLE001
        return
    changed = False
    for node in graph.get("nodes", []):
        if node.get("id") != node_id:
            continue
        data = node.setdefault("data", {})
        if cfg:
            data["model"] = dict(cfg)
        else:
            data.pop("model", None)
        changed = True
        break
    if changed:
        conn.execute("UPDATE canvases SET graph = ? WHERE id = ?",
                     (json.dumps(graph, ensure_ascii=False), canvas_id))


@router.delete("/{canvas_id}/nodes/{node_id}/model")
def clear_node_model(canvas_id: str, node_id: str):
    with get_conn() as conn:
        _fetch(conn, canvas_id)
        conn.execute("DELETE FROM agent_models WHERE canvas_id = ? AND node_id = ?",
                     (canvas_id, node_id))
        _sync_node_model_into_graph(conn, canvas_id, node_id, None)
    return {"ok": True}


@router.delete("/{canvas_id}")
def delete_canvas(canvas_id: str):
    with get_conn() as conn:
        row = _fetch(conn, canvas_id)
        conn.execute("DELETE FROM canvases WHERE id = ?", (canvas_id,))
        conn.execute("DELETE FROM runs WHERE canvas_id = ?", (canvas_id,))
        conn.execute("DELETE FROM agent_models WHERE canvas_id = ?", (canvas_id,))
    target = (PROJECTS_DIR / row["slug"]).resolve()
    if target.parent == PROJECTS_DIR.resolve() and target.exists():
        shutil.rmtree(target, ignore_errors=True)
    remove_background_files(canvas_id)
    return {"ok": True}


def remove_background_files(canvas_id: str) -> int:
    """删掉这个画布上传过的所有背景图（文件名以画布 id 开头）。"""
    if not BACKGROUND_DIR.exists():
        return 0
    removed = 0
    for path in BACKGROUND_DIR.glob(f"{canvas_id}_*"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed
