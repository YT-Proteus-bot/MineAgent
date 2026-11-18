"""把「画布 + 全局」的 provider 配置解析成运行时能直接用的一份。

优先级：画布默认 > 画布任一 > 全局默认 > 全局任一。

返回的配置里含明文密钥，只在内存中流转：
- 写 config.json 时由 generators 剥离，换成 api_key_env；
- 运行时由 run.py 通过环境变量注入子进程。
绝不会把明文写进 projects/ 下的任何文件。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..db import list_providers
from ..security import decrypt
from .catalog import find
from .resolve import build_data_cfg, build_embedding_cfg, build_vector_cfg

# 三类配置在子进程里的环境变量名（每个画布只用一套默认，够用且不串）
ENV_NAMES = {
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


def _pick(kind: str, canvas_id: str) -> Optional[Dict[str, Any]]:
    """按优先级挑一条记录。

    只认「明确设为默认」或「该作用域只有唯一一条」的配置——
    随手建了一条但没启用，不应该悄悄影响所有画布。
    """
    rows = list_providers(kind=kind)
    if not rows:
        return None
    canvas_rows = [r for r in rows
                   if r.get("scope") == "canvas" and r.get("canvas_id") == canvas_id]
    global_rows = [r for r in rows if r.get("scope", "global") == "global"]
    for bucket in (canvas_rows, global_rows):
        defaults = [r for r in bucket if r.get("is_default")]
        if defaults:
            return defaults[0]
        if len(bucket) == 1:
            return bucket[0]
    return None


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


def resolve_runtime_providers(canvas_id: str) -> Dict[str, Dict[str, Any]]:
    """返回 {embedding?: cfg, vector?: cfg, data?: cfg}，含明文密钥。"""
    out: Dict[str, Dict[str, Any]] = {}
    for kind in KINDS:
        row = _pick(kind, canvas_id)
        if not row:
            continue
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
            # 配置不全就跳过，让运行时回退到内置实现，而不是拦住整张画布
            continue
        cfg["api_key_env"] = ENV_NAMES[kind]
        out[kind] = cfg
    return out


def strip_secrets(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """把明文密钥剥掉，只留 api_key_env 名字。写 config.json 前调用。"""
    clean = {k: v for k, v in (cfg or {}).items() if k not in ("api_key", "password", "token", "secret")}
    return clean


def env_bindings(providers: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """把明文密钥转成 {环境变量名: 值}，由 run.py 注入子进程。"""
    out: Dict[str, str] = {}
    for kind, cfg in (providers or {}).items():
        value = cfg.get("api_key") or cfg.get("password") or cfg.get("token") or ""
        if value:
            out[ENV_NAMES.get(kind, f"MINEAGENT_{kind.upper()}_KEY")] = str(value)
    return out


def named_bindings(providers: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """config.json 里给节点用的「按名字取用」清单（不含密钥）。"""
    out: Dict[str, Dict[str, Any]] = {}
    for kind, cfg in (providers or {}).items():
        label = str(cfg.get("provider") or kind)
        out[label] = strip_secrets(cfg)
    return out


__all__: List[str] = [
    "ENV_NAMES", "KINDS", "env_bindings", "named_bindings",
    "resolve_runtime_providers", "strip_secrets",
]
