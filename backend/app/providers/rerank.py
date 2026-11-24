"""重排模型适配层：一套接口，五类协议。

对外只有三个函数：
    rerank_docs(cfg, query, documents, top_n) -> List[Dict]
    probe(cfg)                               -> Dict （连接测试）
    supported_protocols()                    -> List[str]

不同厂商的差别只在「请求字段怎么摆、返回的分数叫什么」，
所以每个协议就是一个把响应归一成 results[{index, score}] 的小函数。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from .base import as_int, http_json, join_url, require
from .errors import ProviderCallError, ProviderConfigError

# 一次最多送检多少条候选：服务商普遍有上限，超了要么报错要么悄悄截断
DEFAULT_MAX_DOCS = 50


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #
def rerank_docs(cfg: Dict[str, Any], query: str, documents: List[str],
                top_n: Optional[int] = None, timeout: float = 60.0) -> List[Dict[str, Any]]:
    """给候选文档打相关性分，按分数从高到低返回 [{index, score, text}]。"""
    docs = [d if isinstance(d, str) else str(d) for d in (documents or [])]
    docs = [d for d in docs if str(d).strip()]
    if not docs:
        return []
    limit = as_int(cfg.get("top_n"), 3) if top_n is None else as_int(top_n, 3)
    limit = max(1, limit)
    max_docs = as_int(cfg.get("max_docs"), DEFAULT_MAX_DOCS) or DEFAULT_MAX_DOCS
    trimmed = docs[:max(1, max_docs)]

    protocol = (cfg.get("protocol") or "").strip().lower()
    scored = _dispatch(protocol, cfg, str(query or ""), trimmed, limit, timeout)

    # 有的服务只回分数、有的连原文一起回；统一按 index 找回原候选
    rows: List[Tuple[int, float]] = []
    for item in scored:
        idx = as_int(item.get("index"), -1)
        if not (0 <= idx < len(trimmed)):
            continue
        rows.append((idx, float(item.get("score") or 0.0)))
    if not rows:
        raise ProviderCallError("重排响应里没有可用的打分结果",
                                detail=str(scored)[:300])
    rows.sort(key=lambda x: x[1], reverse=True)
    return [{"index": idx, "score": round(score, 6), "text": trimmed[idx]}
            for idx, score in rows[:limit]]


def probe(cfg: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
    """连接测试：真的发一次两条候选的重排请求。"""
    started = time.time()
    try:
        hits = rerank_docs(cfg, "连接测试", ["这是一条相关的测试文本", "这是一条无关的测试文本"],
                           top_n=2, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc),
                "hint": getattr(exc, "hint", ""),
                "latency_ms": int((time.time() - started) * 1000)}
    best = hits[0]["score"] if hits else 0.0
    return {
        "ok": True,
        "model": cfg.get("model", ""),
        "protocol": cfg.get("protocol", ""),
        "top_score": round(best, 4),
        "latency_ms": int((time.time() - started) * 1000),
        "message": f"连接成功，返回 {len(hits)} 条重排结果（最高分 {round(best, 4)}）",
    }


# --------------------------------------------------------------------------- #
# 协议分派
# --------------------------------------------------------------------------- #
def _dispatch(protocol: str, cfg: Dict[str, Any], query: str, docs: List[str],
              top_n: int, timeout: float) -> List[Dict[str, Any]]:
    handler = _HANDLERS.get(protocol)
    if handler is None:
        raise ProviderConfigError(
            f"不支持的重排模型协议：{protocol or '（空）'}",
            hint="在配置里选择具体厂商，或选「任意 OpenAI 兼容端点」")
    return handler(cfg, query, docs, top_n, timeout)


def _auth(cfg: Dict[str, Any], header: str = "Authorization",
          prefix: str = "Bearer ") -> Dict[str, str]:
    key = str(cfg.get("api_key") or "").strip()
    return {header: f"{prefix}{key}"} if key else {}


def _pick_results(data: Any) -> List[Dict[str, Any]]:
    """把各家返回的 results / data 数组挑出来。"""
    if isinstance(data, dict):
        for key in ("results", "data", "output"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):  # dashscope: output.results
                inner = value.get("results")
                if isinstance(inner, list):
                    return [row for row in inner if isinstance(row, dict)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _normalize(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """不同厂商的字段名 → {index, score}。"""
    out: List[Dict[str, Any]] = []
    for row in rows:
        idx = row.get("index")
        if idx is None:
            idx = row.get("document_index", row.get("id"))
        raw = None
        for key in ("relevance_score", "score", "relevance", "similarity"):
            if row.get(key) is not None:
                raw = row[key]
                break
        try:
            out.append({"index": int(idx), "score": float(raw)})
        except (TypeError, ValueError):
            continue
    return out


# --------------------------------------------------------------------------- #
# OpenAI 风格 /rerank（Jina / 硅基流动 / vLLM / Xinference / 各家网关）
# --------------------------------------------------------------------------- #
def _openai_rerank(cfg: Dict[str, Any], query: str, docs: List[str],
                   top_n: int, timeout: float) -> List[Dict[str, Any]]:
    base = require(cfg, "base_url", label="Base URL")
    model = require(cfg, "model", label="模型名")
    url = join_url(base, "rerank")
    body: Dict[str, Any] = {
        "model": model, "query": query, "documents": docs,
        "top_n": top_n, "return_documents": False,
    }
    data = http_json(url, body, headers=_auth(cfg), timeout=timeout)
    rows = _pick_results(data)
    if not rows:
        raise ProviderCallError("响应里没有 results 数组", detail=str(data)[:300])
    return _normalize(rows)


# --------------------------------------------------------------------------- #
# Cohere /v2/rerank
# --------------------------------------------------------------------------- #
def _cohere(cfg: Dict[str, Any], query: str, docs: List[str],
            top_n: int, timeout: float) -> List[Dict[str, Any]]:
    base = require(cfg, "base_url", label="Base URL")
    model = require(cfg, "model", label="模型名")
    key = str(cfg.get("api_key") or "").strip()
    if not key:
        raise ProviderConfigError("缺少配置项：API Key", hint="在「API Key」里填写后重试")
    url = join_url(base, "rerank")
    body = {"model": model, "query": query, "documents": docs, "top_n": top_n}
    data = http_json(url, body, headers={"Authorization": f"Bearer {key}"},
                     timeout=timeout)
    rows = _pick_results(data)
    if not rows:
        raise ProviderCallError("Cohere 响应里没有 results", detail=str(data)[:300])
    return _normalize(rows)


# --------------------------------------------------------------------------- #
# Voyage AI（top_k 而不是 top_n）
# --------------------------------------------------------------------------- #
def _voyage(cfg: Dict[str, Any], query: str, docs: List[str],
            top_n: int, timeout: float) -> List[Dict[str, Any]]:
    base = require(cfg, "base_url", label="Base URL")
    model = require(cfg, "model", label="模型名")
    url = join_url(base, "rerank")
    body = {"model": model, "query": query, "documents": docs, "top_k": top_n}
    data = http_json(url, body, headers=_auth(cfg), timeout=timeout)
    rows = _pick_results(data)
    if not rows:
        raise ProviderCallError("Voyage 响应里没有 data", detail=str(data)[:300])
    return _normalize(rows)


# --------------------------------------------------------------------------- #
# 阿里云 DashScope 原生 text-rerank
# --------------------------------------------------------------------------- #
def _dashscope(cfg: Dict[str, Any], query: str, docs: List[str],
               top_n: int, timeout: float) -> List[Dict[str, Any]]:
    base = (require(cfg, "base_url", label="Base URL")).rstrip("/")
    # 允许用户填成兼容模式地址，这里自动换算成原生路径
    if "/compatible-mode" in base:
        base = base.split("/compatible-mode")[0]
    if not base.endswith("/api/v1"):
        base = join_url(base, "api/v1")
    url = join_url(base, "services/rerank/text-rerank/text-rerank")
    model = require(cfg, "model", label="模型名")
    body = {
        "model": model,
        "input": {"query": query, "documents": docs},
        "parameters": {"return_documents": False, "top_n": top_n},
    }
    data = http_json(url, body, headers=_auth(cfg), timeout=timeout)
    if isinstance(data, dict) and data.get("code"):
        raise ProviderCallError(f"DashScope 返回错误：{data.get('code')}",
                                detail=str(data.get("message", ""))[:300])
    rows = _pick_results(data)
    if not rows:
        raise ProviderCallError("DashScope 响应里没有 output.results", detail=str(data)[:300])
    return _normalize(rows)


# --------------------------------------------------------------------------- #
# HuggingFace TEI /rerank（texts 而不是 documents，没有 top_n）
# --------------------------------------------------------------------------- #
def _tei(cfg: Dict[str, Any], query: str, docs: List[str],
         top_n: int, timeout: float) -> List[Dict[str, Any]]:
    base = require(cfg, "base_url", label="服务地址").rstrip("/")
    url = join_url(base, "rerank")
    body = {"query": query, "texts": docs, "truncate": True, "raw_scores": False}
    data = http_json(url, body, headers=_auth(cfg), timeout=timeout)
    rows = _pick_results(data)
    if not rows:
        raise ProviderCallError("TEI 响应格式不符合预期", detail=str(data)[:300])
    return _normalize(rows)


_HANDLERS = {
    "openai_rerank": _openai_rerank,
    "cohere": _cohere,
    "voyage": _voyage,
    "dashscope": _dashscope,
    "tei": _tei,
}


def supported_protocols() -> List[str]:
    return sorted(_HANDLERS)
