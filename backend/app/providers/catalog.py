"""四类枚举的统一入口。

前端只调 /api/providers/catalog 拿这一份，后端 CRUD / 连接测试 / 适配器
分派也都从这里查。新增厂商只改 catalog_*.py。
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .catalog_data import DATA
from .catalog_embedding import EMB
from .catalog_rerank import RERANK
from .catalog_vector import VEC

KINDS: Dict[str, Dict[str, Any]] = {
    "embedding": {
        "label": "向量模型",
        "desc": "把文本转成向量，建库和查询必须用同一个模型。",
        "items": EMB,
    },
    "rerank": {
        "label": "重排模型",
        "desc": "拿到召回候选后逐条打相关性分再排序，决定最终喂给模型的前几条。",
        "items": RERANK,
    },
    "vector": {
        "label": "向量库",
        "desc": "存向量和原文，按相似度检索。内置 SQLite 兜底，也支持外部库。",
        "items": VEC,
    },
    "data": {
        "label": "数据源",
        "desc": "业务库、文档库、图库、缓存、时序库，供节点读写。",
        "items": DATA,
    },
}

GROUPS: Dict[str, str] = {
    "builtin": "内置",
    "self_hosted": "开源 / 自部署",
    "cloud": "云托管",
    "local": "本地 / 自部署推理",
    "inproc": "进程内推理",
    "relational": "关系型",
    "document": "文档型",
    "graph": "图数据库",
    "kv": "KV / 缓存",
    "timeseries": "时序",
}


def _clean(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """深拷贝后再补默认值，避免多条 entry 共享同一个 fields 列表。"""
    out: List[Dict[str, Any]] = []
    for item in items:
        entry = copy.deepcopy(item)
        entry.setdefault("group", "cloud")
        entry.setdefault("status", "ready")
        entry.setdefault("pip", "")
        entry.setdefault("help", "")
        entry.setdefault("base_url", "")
        entry.setdefault("key_required", True)
        entry.setdefault("protocol", entry["id"])
        entry.setdefault("models", [])
        entry.setdefault("fields", [])
        out.append(entry)
    return out


_CLEANED: Dict[str, List[Dict[str, Any]]] = {}


def items_of(kind: str) -> List[Dict[str, Any]]:
    if kind not in _CLEANED:
        raw = KINDS.get(kind, {}).get("items", [])
        _CLEANED[kind] = _clean(raw)
    return _CLEANED[kind]


def find(kind: str, provider_id: str) -> Optional[Dict[str, Any]]:
    for item in items_of(kind):
        if item["id"] == provider_id:
            return item
    return None


def public_catalog() -> Dict[str, Any]:
    """给前端的目录：带上分组中英文名，字段里不含任何密钥值。"""
    return {
        "groups": GROUPS,
        "kinds": [
            {
                "id": kind,
                "label": meta["label"],
                "desc": meta["desc"],
                "items": items_of(kind),
            }
            for kind, meta in KINDS.items()
        ],
    }


def secret_fields(kind: str, provider_id: str) -> List[str]:
    """这个 provider 的哪些配置字段需要单独加密。"""
    item = find(kind, provider_id)
    if not item:
        return []
    return [f["key"] for f in item.get("fields", []) if f.get("secret")]


def default_config(kind: str, provider_id: str) -> Dict[str, Any]:
    """按字段定义组装一份默认配置，新建表单时用。"""
    item = find(kind, provider_id)
    if not item:
        return {}
    cfg: Dict[str, Any] = {}
    if item.get("base_url"):
        cfg["base_url"] = item["base_url"]
    for f in item.get("fields", []):
        if f.get("secret"):
            continue
        cfg[f["key"]] = f.get("default", "")
    models_list = item.get("models") or []
    if models_list and not cfg.get("model"):
        cfg["model"] = models_list[0]["id"]
        cfg["dim"] = models_list[0].get("dim", 0)
    return cfg
