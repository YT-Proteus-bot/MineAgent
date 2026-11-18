"""枚举目录的公共工具。

这里的清单是「纯数据」：新增一家厂商 / 一个库，只需要在对应的 catalog_*.py
里加一个 entry，不需要改任何逻辑代码。前端的下拉、表单、连接测试、文档
全部从这份数据派生，保证「三处一致」。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def F(key: str, label: str, *, required: bool = False, secret: bool = False,
      default: Any = "", placeholder: str = "", kind: str = "text",
      options: Optional[List[str]] = None, help_text: str = "") -> Dict[str, Any]:
    """一个配置字段。

    kind: text / password / number / select / textarea
    secret=True 的字段会被单独加密存储，接口只回显掩码。
    """
    item: Dict[str, Any] = {
        "key": key,
        "label": label,
        "required": bool(required),
        "secret": bool(secret),
        "default": default,
        "placeholder": placeholder,
        "kind": kind,
        "help": help_text,
    }
    if options:
        item["options"] = options
    return item


def models(spec: str) -> List[Dict[str, Any]]:
    """把 "model-id:dim, other:0" 解析成模型清单，dim=0 表示运行时探测。"""
    out: List[Dict[str, Any]] = []
    for chunk in (spec or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            mid, _, dim = chunk.rpartition(":")
            try:
                dim_i = int(dim)
            except ValueError:
                mid, dim_i = chunk, 0
        else:
            mid, dim_i = chunk, 0
        mid = mid.strip()
        if mid:
            out.append({"id": mid, "dim": dim_i})
    return out


# 几乎所有 embedding 服务共用的字段集
BASE_EMBEDDING_FIELDS: List[Dict[str, Any]] = [
    F("base_url", "Base URL", required=True, placeholder="https://api.example.com/v1",
      help_text="兼容 OpenAI 时必须带 /v1"),
    F("model", "模型名", required=True, placeholder="text-embedding-3-small"),
    F("dim", "向量维度", kind="number", default=0,
      help_text="0 表示首次调用时自动探测；填错会导致检索结果异常"),
    F("batch_size", "单次批量", kind="number", default=32,
      help_text="一次请求带多少条文本，服务商多有上限"),
    F("api_key", "API Key", secret=True, placeholder="sk-..."),
]
