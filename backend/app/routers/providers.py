"""向量模型 / 向量库 / 数据源 的配置接口。

约定与「模型配置」一致：
- 密文字段单独加密落库，接口永不回显明文，只回显掩码；
- 连接测试既支持已保存的记录，也支持还没保存的草稿（前端边填边测）；
- 目录（厂商清单）由 providers.catalog 统一提供，前端不硬编码。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from ..config import DATA_DIR
from ..db import (clear_provider_default, delete_provider, get_provider,
                  list_providers, save_provider)
from ..providers import (ProviderError, build_data_cfg, build_embedding_cfg,
                         build_vector_cfg, find, get_database, get_store,
                         probe_embedding, public_catalog, secret_fields)
from ..schemas import ProviderIn, ProviderOut, ProviderTestIn
from ..security import decrypt, encrypt, mask

router = APIRouter(prefix="/api/providers", tags=["providers"])

PROVIDER_DIR = DATA_DIR / "providers"


# --------------------------------------------------------------------------- #
# 目录
# --------------------------------------------------------------------------- #
@router.get("/catalog")
def catalog():
    """三类清单：向量模型 / 向量库 / 数据源，含字段定义与默认值。"""
    return public_catalog()


# --------------------------------------------------------------------------- #
# 读写
# --------------------------------------------------------------------------- #
def _secret_dict(cipher: str) -> Dict[str, Any]:
    if not cipher:
        return {}
    raw = decrypt(cipher)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _to_out(row: Dict[str, Any]) -> ProviderOut:
    item = find(row["kind"], row["provider"]) or {}
    secrets = _secret_dict(row.get("secret_cipher", ""))
    try:
        config = json.loads(row.get("config") or "{}")
    except json.JSONDecodeError:
        config = {}
    return ProviderOut(
        id=row["id"], kind=row["kind"], provider=row["provider"],
        name=row.get("name") or item.get("label") or row["provider"],
        label=item.get("label", ""), config=config,
        secret_mask={k: mask(str(v)) for k, v in secrets.items()},
        scope=row.get("scope", "global"), canvas_id=row.get("canvas_id", ""),
        is_default=bool(row.get("is_default")),
        status=item.get("status", "ready"),
        created_at=row.get("created_at", ""), updated_at=row.get("updated_at", ""),
    )


@router.get("", response_model=List[ProviderOut])
def list_all(kind: str = "", canvas_id: str = ""):
    rows = list_providers(kind=kind, canvas_id=canvas_id)
    return [_to_out(row) for row in rows]


@router.post("", response_model=ProviderOut)
def create(payload: ProviderIn):
    if find(payload.kind, payload.provider) is None:
        raise HTTPException(status_code=400,
                            detail=f"未知的 {payload.kind} 类型：{payload.provider}")
    # 向量模型 / 向量库 / 数据源都是画布级配置
    if not payload.canvas_id:
        raise HTTPException(status_code=400, detail="缺少 canvas_id：这些配置属于具体画布")
    pid = uuid.uuid4().hex[:16]
    record = {
        "id": pid,
        "kind": payload.kind,
        "provider": payload.provider,
        "name": payload.name or (find(payload.kind, payload.provider) or {}).get("label", ""),
        "config": json.dumps(payload.config or {}, ensure_ascii=False),
        "secret_cipher": _seal(payload.secret),
        "scope": "canvas",
        "canvas_id": payload.canvas_id,
        "is_default": 1 if payload.is_default else 0,
    }
    if record["is_default"]:
        clear_provider_default(record["kind"], record["scope"], record["canvas_id"])
    save_provider(record)
    return _to_out(get_provider(pid) or record)


@router.put("/{provider_id}", response_model=ProviderOut)
def update(provider_id: str, payload: ProviderIn):
    row = get_provider(provider_id)
    if row is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    if payload.provider and find(payload.kind, payload.provider) is None:
        raise HTTPException(status_code=400,
                            detail=f"未知的 {payload.kind} 类型：{payload.provider}")

    kind = payload.kind or row["kind"]
    provider = payload.provider or row["provider"]
    # secret 为 None 表示「不改」，空 dict 表示「清空」
    cipher = row.get("secret_cipher", "")
    if payload.secret is not None:
        merged = {**_secret_dict(cipher), **payload.secret}
        merged = {k: v for k, v in merged.items() if str(v).strip()}
        cipher = _seal(merged) if merged else ""

    record = {
        "id": provider_id,
        "kind": kind,
        "provider": provider,
        "name": payload.name or row.get("name", ""),
        "config": json.dumps(payload.config or {}, ensure_ascii=False),
        "secret_cipher": cipher,
        # 画布归属不随编辑变化
        "scope": row.get("scope", "canvas"),
        "canvas_id": row.get("canvas_id", ""),
        "is_default": 1 if payload.is_default else 0,
        "created_at": row.get("created_at", ""),
    }
    if record["is_default"]:
        clear_provider_default(record["kind"], record["scope"], record["canvas_id"])
    save_provider(record)
    return _to_out(get_provider(provider_id) or record)


@router.post("/{provider_id}/default", response_model=ProviderOut)
def set_default(provider_id: str):
    row = get_provider(provider_id)
    if row is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    clear_provider_default(row["kind"], row.get("scope", "global"),
                           row.get("canvas_id", ""))
    row["is_default"] = 1
    save_provider(row)
    return _to_out(get_provider(provider_id) or row)


@router.delete("/{provider_id}")
def remove(provider_id: str):
    if not delete_provider(provider_id):
        raise HTTPException(status_code=404, detail="配置不存在")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# 连接测试
# --------------------------------------------------------------------------- #
@router.post("/test")
def test_connection(payload: ProviderTestIn):
    """真发一次请求：向量模型打一条 ping、向量库列集合、数据库连一下。"""
    row: Dict[str, Any] = {}
    if payload.id:
        row = get_provider(payload.id) or {}
    kind = payload.kind or row.get("kind", "")
    provider = payload.provider or row.get("provider", "")
    if not provider:
        raise HTTPException(status_code=400, detail="请选择具体厂商/库")

    item = find(kind, provider)
    if item is None:
        raise HTTPException(status_code=400, detail=f"未知的 {kind} 类型：{provider}")
    if item.get("status") == "planned":
        return {"ok": False, "stage": "planned",
                "message": f"「{item.get('label')}」已列入清单，但适配器还没实现"}

    # 已存记录里的密文兜底，草稿里填的优先
    secrets = _secret_dict(row.get("secret_cipher", ""))
    secrets.update(payload.secret or {})
    config = json.loads(row.get("config") or "{}") if row else {}
    config.update(payload.config or {})
    record = {"kind": kind, "provider": provider, "config": config, "secret": secrets}

    try:
        if kind == "embedding":
            cfg = build_embedding_cfg(record)
            result = probe_embedding(cfg)
            result["protocol"] = cfg.get("protocol")
        elif kind == "vector":
            base_dir = PROVIDER_DIR / (payload.id or uuid.uuid4().hex[:8])
            base_dir.mkdir(parents=True, exist_ok=True)
            store = get_store(build_vector_cfg(record, base_dir=str(base_dir)))
            result = store.probe()
            result["protocol"] = store.protocol
        elif kind == "data":
            cfg = build_data_cfg(record)
            cfg["base_dir"] = str(PROVIDER_DIR)
            db = get_database(cfg)
            result = db.probe()
            result["protocol"] = db.protocol
            result["tables"] = db.collections()[:30]
        else:
            raise HTTPException(status_code=400, detail=f"未知类型：{kind}")
    except ProviderError as exc:
        return {"ok": False, "stage": item.get("status", "ready"),
                "message": exc.message, "hint": exc.hint,
                "error": exc.__class__.__name__}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "stage": item.get("status", "ready"),
                "message": f"测试失败：{exc}", "error": exc.__class__.__name__}

    result.setdefault("ok", True)
    result["stage"] = item.get("status", "ready")
    return result


# --------------------------------------------------------------------------- #
# 内部
# --------------------------------------------------------------------------- #
def _seal(secret: Optional[Dict[str, Any]]) -> str:
    if not secret:
        return ""
    clean = {k: v for k, v in secret.items() if v is not None and str(v).strip()}
    return encrypt(json.dumps(clean, ensure_ascii=False)) if clean else ""
