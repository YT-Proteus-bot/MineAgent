"""画布级数据中台：数据集登记、列预览、表清单。

数据源本身复用 `providers` 表（kind='data'，scope='canvas'），这里只做「数据集」这一层：
把某个数据源里的表或查询登记成逻辑名，节点里就能按名字取数。

隔离：所有查询都带 canvas_id，数据集只能引用同一张画布下的数据源。
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import DATA_DIR
from ..db import get_conn, get_provider, now_iso
from ..providers import ProviderError, build_data_cfg, get_database
from ..security import decrypt

router = APIRouter(prefix="/api/canvases/{canvas_id}/data", tags=["datahub"])

PROVIDER_DIR = DATA_DIR / "providers"
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
LOGICAL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
WRITE_WORDS = ("insert ", "update ", "delete ", "drop ", "alter ", "create ", "truncate ", "grant ")


class DatasetIn(BaseModel):
    logical: str = Field(default="", description="节点里用的名字，如 orders")
    source_id: str = ""
    kind: str = Field(default="table", description="table | sql")
    spec: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    mode: str = Field(default="read", description="read | write")
    columns: List[str] = Field(default_factory=list)


def _canvas(canvas_id: str) -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM canvases WHERE id = ?", (canvas_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "画布不存在")
    return dict(row)


def _source(canvas_id: str, source_id: str) -> Dict[str, Any]:
    record = get_provider(source_id)
    if not record or record.get("kind") != "data":
        raise HTTPException(404, "数据源不存在")
    if record.get("canvas_id") and record.get("canvas_id") != canvas_id:
        raise HTTPException(404, "数据源不属于这张画布")
    return record


def _database(record: Dict[str, Any]):
    """按数据源记录建一个可用连接；失败时把厂商的报错原样抛给前端。"""
    try:
        config = json.loads(record.get("config") or "{}")
    except json.JSONDecodeError:
        config = {}
    try:
        secrets = json.loads(decrypt(record.get("secret_cipher") or "") or "{}")
    except Exception:  # noqa: BLE001
        secrets = {}
    cfg = build_data_cfg({"kind": "data", "provider": record.get("provider", ""),
                          "config": config, "secret": secrets})
    cfg["base_dir"] = str(PROVIDER_DIR)
    try:
        return get_database(cfg)
    except ProviderError as exc:
        raise HTTPException(400, {"error": exc.message, "hint": getattr(exc, "hint", "")}) from exc


def _dataset_row(canvas_id: str, dataset_id: str) -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM datasets WHERE id = ? AND canvas_id = ?",
                           (dataset_id, canvas_id)).fetchone()
    if row is None:
        raise HTTPException(404, "数据集不存在")
    return dict(row)


def _public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    try:
        out["spec"] = json.loads(out.get("spec") or "{}")
    except json.JSONDecodeError:
        out["spec"] = {}
    try:
        out["columns"] = json.loads(out.get("columns") or "[]")
    except json.JSONDecodeError:
        out["columns"] = []
    return out


def _validate(payload: DatasetIn) -> Dict[str, Any]:
    logical = (payload.logical or "").strip()
    if not LOGICAL.match(logical):
        raise HTTPException(400, "数据集名只能包含字母、数字、下划线，且不能以数字开头")
    kind = (payload.kind or "table").strip().lower()
    if kind not in ("table", "sql"):
        raise HTTPException(400, "目前只支持 table / sql 两种数据集")
    spec = dict(payload.spec or {})
    if kind == "table":
        table = str(spec.get("table") or "").strip()
        if not IDENT.match(table):
            raise HTTPException(400, "表名不合法（支持 schema.table 形式）")
        spec = {"table": table}
    else:
        sql = str(spec.get("sql") or "").strip().rstrip(";").strip()
        if not sql:
            raise HTTPException(400, "SQL 不能为空")
        if ";" in sql:
            raise HTTPException(400, "只允许单条 SQL，不要带分号或多语句")
        if sql.lower().lstrip().startswith(WRITE_WORDS):
            raise HTTPException(400, "数据集只允许查询语句（select / with）")
        spec = {"sql": sql}
    mode = (payload.mode or "read").strip().lower()
    if mode not in ("read", "write"):
        raise HTTPException(400, "mode 只能是 read 或 write")
    return {"logical": logical, "kind": kind, "spec": spec, "mode": mode,
            "source_id": (payload.source_id or "").strip(),
            "description": (payload.description or "").strip()[:500],
            "columns": [str(c)[:64] for c in (payload.columns or [])][:80]}


@router.get("")
def list_datasets(canvas_id: str) -> Dict[str, Any]:
    _canvas(canvas_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM datasets WHERE canvas_id = ? ORDER BY updated_at DESC",
            (canvas_id,)).fetchall()
        sources = conn.execute(
            "SELECT id, provider, name, config, scope FROM providers "
            "WHERE kind = 'data' AND (canvas_id = ? OR scope = 'global') ORDER BY updated_at DESC",
            (canvas_id,)).fetchall()
    return {"datasets": [_public(dict(r)) for r in rows],
            "sources": [dict(r) for r in sources]}


@router.post("")
def create_dataset(canvas_id: str, payload: DatasetIn) -> Dict[str, Any]:
    _canvas(canvas_id)
    data = _validate(payload)
    _source(canvas_id, data["source_id"])
    dataset_id = uuid.uuid4().hex
    now = now_iso()
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO datasets(id, canvas_id, source_id, logical, kind, spec, columns,"
                " mode, description, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (dataset_id, canvas_id, data["source_id"], data["logical"], data["kind"],
                 json.dumps(data["spec"], ensure_ascii=False),
                 json.dumps(data["columns"], ensure_ascii=False), data["mode"],
                 data["description"], now, now))
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(409, f"数据集名「{data['logical']}」已存在") from exc
        raise
    return _public(_dataset_row(canvas_id, dataset_id))


@router.put("/{dataset_id}")
def update_dataset(canvas_id: str, dataset_id: str, payload: DatasetIn) -> Dict[str, Any]:
    current = _dataset_row(canvas_id, dataset_id)
    data = _validate(payload)
    if data["source_id"]:
        _source(canvas_id, data["source_id"])
    else:
        data["source_id"] = current["source_id"]
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE datasets SET source_id=?, logical=?, kind=?, spec=?, columns=?,"
                " mode=?, description=?, updated_at=? WHERE id=? AND canvas_id=?",
                (data["source_id"], data["logical"], data["kind"],
                 json.dumps(data["spec"], ensure_ascii=False),
                 json.dumps(data["columns"] or _public(current)["columns"], ensure_ascii=False),
                 data["mode"], data["description"], now_iso(), dataset_id, canvas_id))
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(409, f"数据集名「{data['logical']}」已存在") from exc
        raise
    return _public(_dataset_row(canvas_id, dataset_id))


@router.delete("/{dataset_id}")
def delete_dataset(canvas_id: str, dataset_id: str) -> Dict[str, Any]:
    _dataset_row(canvas_id, dataset_id)
    with get_conn() as conn:
        conn.execute("DELETE FROM datasets WHERE id = ? AND canvas_id = ?",
                     (dataset_id, canvas_id))
        conn.commit()
    return {"ok": True}


@router.get("/sources/{source_id}/tables")
def list_tables(canvas_id: str, source_id: str) -> Dict[str, Any]:
    record = _source(canvas_id, source_id)
    db = _database(record)
    try:
        tables = db.collections()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"读取表清单失败：{exc}") from exc
    return {"tables": tables[:200]}


@router.get("/refs")
def list_refs(canvas_id: str) -> Dict[str, Any]:
    """节点「数据接入」下拉的可选项：本画布数据集 + 数据源 + 外部接入映射。"""
    row = _canvas(canvas_id)
    with get_conn() as conn:
        datasets = conn.execute(
            "SELECT id, logical, kind, mode FROM datasets WHERE canvas_id = ? ORDER BY logical",
            (canvas_id,)).fetchall()
        sources = conn.execute(
            "SELECT id, name, provider FROM providers WHERE kind = 'data' "
            "AND (canvas_id = ? OR scope = 'global') ORDER BY name",
            (canvas_id,)).fetchall()
    try:
        service = json.loads(row.get("graph") or "{}").get("service") or {}
    except json.JSONDecodeError:
        service = {}
    remote = (service.get("data") or {}).get("datasets") or []
    return {
        "datasets": [dict(r) for r in datasets],
        "sources": [dict(r) for r in sources],
        "remote": [r for r in remote if isinstance(r, dict) and r.get("logical")],
    }


@router.get("/datasets/{dataset_id}/preview")
def preview(canvas_id: str, dataset_id: str, limit: int = 20) -> Dict[str, Any]:
    row = _dataset_row(canvas_id, dataset_id)
    record = _source(canvas_id, row["source_id"])
    dataset = _public(row)
    limit = max(1, min(int(limit or 20), 200))
    spec = dataset["spec"]
    if dataset["kind"] == "table":
        statement = f"SELECT * FROM {spec.get('table', '')} LIMIT {limit}"
    else:
        statement = f"SELECT * FROM ({spec.get('sql', '')}) AS _preview LIMIT {limit}"
    db = _database(record)
    try:
        rows = db.query(statement)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"查询失败：{exc}") from exc
    rows = [dict(r) for r in (rows or [])][:limit]
    columns = list(rows[0].keys()) if rows else list(dataset.get("columns") or [])
    if columns and columns != dataset.get("columns"):
        with get_conn() as conn:
            conn.execute("UPDATE datasets SET columns = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(columns, ensure_ascii=False), now_iso(), dataset_id))
            conn.commit()
    return {"columns": columns, "rows": rows, "row_count": len(rows),
            "statement": statement, "mode": dataset["mode"]}
