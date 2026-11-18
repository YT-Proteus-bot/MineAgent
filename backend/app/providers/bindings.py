"""把画布的 provider 配置解析成运行时能直接用的一份。

配置完全属于画布：同一张画布可以有多套向量模型 / 向量库 / 数据源，
每种类型有一个「默认」，节点参数里可以用实例名覆盖。

返回结构（写进 config.json 的也是它，密钥除外）：

    {
      "embedding": {"default": "OpenAI 小模型", "items": {"OpenAI 小模型": {...}}},
      "vector":    {"default": "本地 Chroma",   "items": {...}},
      "data":      {"default": "",             "items": {...}}
    }

返回的配置里含明文密钥，只在内存中流转：
- 写 config.json 时由 generators 剥离，换成 api_key_env；
- 运行时由 run.py 通过环境变量注入子进程。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..db import list_providers
from ..security import decrypt
from .catalog import find
from .resolve import build_data_cfg, build_embedding_cfg, build_vector_cfg

# 环境变量前缀：每个实例一个，序号在 _env_names 里定
ENV_PREFIX = {
    "embedding": "MINEAGENT_EMB_KEY",
    "vector": "MINEAGENT_VEC_KEY",
    "data": "MINEAGENT_DATA_KEY",
}

KINDS = ("embedding", "vector", "data")


def _secret(row: Dict[str, Any]) -> Dict[str, Any]:
    cipher = row.get("secret_cipher") or ""
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


def _to_record(row: Dict[str, Any]) -> Dict[str, Any]:
    try:
        config = json.loads(row.get("config") or "{}")
    except json.JSONDecodeError:
        config = {}
    return {
        "kind": row["kind"],
        "provider": row["provider"],
        "config": config,
        "secret": _secret(row),
    }


def _unique_name(name: str, taken: set) -> str:
    """实例名去重：重名时加 #2、#3。"""
    base = (name or "未命名").strip() or "未命名"
    candidate = base
    idx = 2
    while candidate in taken:
        candidate = f"{base} #{idx}"
        idx += 1
    taken.add(candidate)
    return candidate


def _rows_for_canvas(canvas_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """按类型分组。

    只认这个画布自己的配置；历史上留在 global 的记录也会被带进来
    （老数据平滑过渡），但新建的一律是 canvas 作用域。
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {k: [] for k in KINDS}
    for row in list_providers(canvas_id=canvas_id):
        kind = row.get("kind")
        if kind not in grouped:
            continue
        # 画布专属 + 老全局记录（global 只作为迁移兼容）
        if row.get("scope") == "canvas" and row.get("canvas_id") != canvas_id:
            continue
        grouped[kind].append(row)
    return grouped


def resolve_runtime_providers(canvas_id: str) -> Dict[str, Dict[str, Any]]:
    """返回 {kind: {"default": name, "items": {name: cfg}}}，cfg 含明文密钥。"""
    grouped = _rows_for_canvas(canvas_id)
    out: Dict[str, Dict[str, Any]] = {}

    for kind in KINDS:
        rows = grouped.get(kind) or []
        if not rows:
            continue
        items: Dict[str, Any] = {}
        default_name = ""
        taken: set = set()
        # 默认项排前面，保证「第一条」就是默认
        rows.sort(key=lambda r: (0 if r.get("is_default") else 1, r.get("created_at") or ""))
        for row in rows:
            record = _to_record(row)
            if find(kind, record["provider"]) is None:
                continue
            try:
                if kind == "embedding":
                    cfg = build_embedding_cfg(record)
                elif kind == "vector":
                    cfg = build_vector_cfg(record)
                else:
                    cfg = build_data_cfg(record)
            except Exception:  # noqa: BLE001
                # 配置不全就跳过，不让一张画布被一条坏配置卡死
                continue
            name = _unique_name(row.get("name") or record["provider"], taken)
            cfg["_name"] = name
            items[name] = cfg
            if not default_name:
                default_name = name
        if items:
            out[kind] = {"default": default_name, "items": items}
    return out


def _env_names(providers: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """给每个实例分配一个环境变量名：{kind: {实例名: ENV}}。"""
    out: Dict[str, Dict[str, str]] = {}
    for kind, block in (providers or {}).items():
        prefix = ENV_PREFIX.get(kind, f"MINEAGENT_{kind.upper()}_KEY")
        names: Dict[str, str] = {}
        for idx, name in enumerate((block.get("items") or {}).keys(), start=1):
            names[name] = f"{prefix}_{idx}" if idx > 1 else prefix
        out[kind] = names
    return out


def strip_secrets(providers: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """剥掉明文密钥、写入环境变量名，产出可以落进 config.json 的结构。"""
    envs = _env_names(providers)
    clean: Dict[str, Any] = {}
    for kind, block in (providers or {}).items():
        items_in = block.get("items") or {}
        items_out: Dict[str, Any] = {}
        for name, cfg in items_in.items():
            entry = {k: v for k, v in cfg.items()
                     if k not in ("api_key", "password", "token", "secret")}
            entry["api_key_env"] = envs.get(kind, {}).get(name, "")
            items_out[name] = entry
        clean[kind] = {"default": block.get("default") or "", "items": items_out}
    return clean


def env_bindings(providers: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """把每个实例的明文密钥转成 {环境变量名: 值}，由 run.py 注入子进程。"""
    envs = _env_names(providers)
    out: Dict[str, str] = {}
    for kind, block in (providers or {}).items():
        for name, cfg in (block.get("items") or {}).items():
            value = cfg.get("api_key") or cfg.get("password") or cfg.get("token") or ""
            env_name = envs.get(kind, {}).get(name)
            if value and env_name:
                out[env_name] = str(value)
    return out


__all__: List[str] = [
    "ENV_PREFIX", "KINDS", "env_bindings", "resolve_runtime_providers",
    "strip_secrets",
]
