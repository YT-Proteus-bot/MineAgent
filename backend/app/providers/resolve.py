"""把「存库的 provider 记录」翻译成「适配器能直接吃的 cfg」。

数据库里一行长这样：
    {id, kind, provider, name, config: {...非密文字段...}, secret: {...密文字段解密后...}}

catalog 里一条长这样：
    {id, protocol, base_url, fields:[...], models:[...]}

本模块负责把两者合并成适配器需要的最终配置，并补齐协议字段。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .catalog import default_config, find
from .errors import ProviderConfigError


def _merge(record: Dict[str, Any]) -> Dict[str, Any]:
    """默认值 ← 用户存的 config ← 解密后的 secret，后者优先级最高。"""
    kind = (record.get("kind") or "").strip()
    provider = (record.get("provider") or "").strip()
    item = find(kind, provider)
    if item is None:
        raise ProviderConfigError(
            f"未知的 {kind} 类型：{provider or '（空）'}",
            hint="重新在「向量模型 / 向量库 / 数据源」里选择一次")

    cfg: Dict[str, Any] = {"provider": provider, "protocol": item["protocol"]}
    for key, value in (default_config(kind, provider) or {}).items():
        cfg[key] = value
    cfg.update(record.get("config") or {})
    cfg.update(record.get("secret") or {})
    cfg = {k: v for k, v in cfg.items() if v is not None}
    return cfg


def build_embedding_cfg(record: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _merge(record)
    if not cfg.get("model"):
        raise ProviderConfigError("向量模型还没填模型名",
                                  hint="在向量模型配置里填 model，例如 text-embedding-3-small")
    return cfg


def build_vector_cfg(record: Dict[str, Any],
                     base_dir: Optional[str] = None) -> Dict[str, Any]:
    cfg = _merge(record)
    if base_dir:
        cfg["base_dir"] = str(base_dir)
    return cfg


def build_data_cfg(record: Dict[str, Any]) -> Dict[str, Any]:
    return _merge(record)
