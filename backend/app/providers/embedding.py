"""向量模型适配层：一套接口，六类协议。

对外只有三个函数：
    embed_texts(cfg, texts)   -> List[List[float]]
    embed_query(cfg, text)    -> List[float]
    probe(cfg)                -> Dict   （连接测试 + 维度探测）

cfg 里的 protocol 决定走哪套协议；protocol 由 catalog_embedding.py 声明。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from .base import (as_int, batches, http_json, join_url, lazy_import,
                   require)
from .errors import ProviderCallError, ProviderConfigError

# 进程内模型加载很贵，同一个 (protocol, model) 只加载一次
_MODEL_CACHE: Dict[str, Any] = {}


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #
def embed_texts(cfg: Dict[str, Any], texts: List[str], *,
                input_type: str = "document") -> List[List[float]]:
    """把一批文本转成向量，返回顺序与入参一致。

    input_type 只对少数协议有意义（Cohere / Jina / Voyage 区分 document 和 query）。
    """
    clean = [t if isinstance(t, str) else str(t) for t in (texts or [])]
    if not clean:
        return []
    protocol = (cfg.get("protocol") or "").strip().lower()
    batch_size = as_int(cfg.get("batch_size"), 32) or 32

    out: List[List[float]] = []
    for chunk in batches(clean, batch_size):
        vectors = _dispatch(protocol, cfg, chunk, input_type)
        if len(vectors) != len(chunk):
            raise ProviderCallError(
                f"返回条数不匹配：期望 {len(chunk)}，实际 {len(vectors)}")
        out.extend(vectors)
    return out


def embed_query(cfg: Dict[str, Any], text: str) -> List[float]:
    vectors = embed_texts(cfg, [text], input_type="query")
    return vectors[0] if vectors else []


def probe(cfg: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
    """连接测试：真的发一次 embedding 请求，并报告维度与耗时。"""
    started = time.time()
    protocol = (cfg.get("protocol") or "").strip().lower()
    try:
        vectors = _dispatch(protocol, cfg, ["ping"], "query", timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc),
                "hint": getattr(exc, "hint", ""),
                "latency_ms": int((time.time() - started) * 1000)}
    dim = len(vectors[0]) if vectors else 0
    declared = as_int(cfg.get("dim"), 0)
    warn = ""
    if declared and dim and declared != dim:
        warn = f"；注意：配置里写的是 {declared} 维，实际返回 {dim} 维，建议改成 {dim}"
    return {
        "ok": True,
        "dim": dim,
        "declared_dim": declared,
        "model": cfg.get("model", ""),
        "latency_ms": int((time.time() - started) * 1000),
        "message": f"连接成功，模型 {cfg.get('model', '')} 返回 {dim} 维向量{warn}",
    }


# --------------------------------------------------------------------------- #
# 协议分派
# --------------------------------------------------------------------------- #
def _dispatch(protocol: str, cfg: Dict[str, Any], texts: List[str],
              input_type: str, timeout: float = 60.0) -> List[List[float]]:
    handler = _HANDLERS.get(protocol)
    if handler is None:
        raise ProviderConfigError(
            f"不支持的向量模型协议：{protocol or '（空）'}",
            hint="在配置里选择具体厂商，或选「任意 OpenAI 兼容端点」")
    return handler(cfg, texts, input_type, timeout)


# --------------------------------------------------------------------------- #
# OpenAI 兼容（覆盖绝大多数云端与自部署服务）
# --------------------------------------------------------------------------- #
def _openai(cfg: Dict[str, Any], texts: List[str], input_type: str,
            timeout: float) -> List[List[float]]:
    base = require(cfg, "base_url", label="Base URL")
    model = require(cfg, "model", label="模型名")
    url = join_url(base, "embeddings")
    headers = {"Authorization": f"Bearer {cfg.get('api_key') or 'none'}"}
    body: Dict[str, Any] = {"model": model, "input": texts}
    # 少数服务把「查询/文档」也做成字段，不认就忽略，不会报错
    if input_type and cfg.get("send_input_type"):
        body["input_type"] = input_type

    data = http_json(url, body, headers=headers, timeout=timeout)
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ProviderCallError("响应里没有 data 数组",
                                detail=str(data)[:300])
    # 按 index 排序，防止服务端乱序
    indexed: List[tuple[int, List[float]]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        vec = row.get("embedding")
        if isinstance(vec, list):
            indexed.append((as_int(row.get("index"), i), [float(x) for x in vec]))
    indexed.sort(key=lambda x: x[0])
    return [v for _, v in indexed]


# --------------------------------------------------------------------------- #
# Azure OpenAI（路径与鉴权都不同）
# --------------------------------------------------------------------------- #
def _azure(cfg: Dict[str, Any], texts: List[str], input_type: str,
           timeout: float) -> List[List[float]]:
    endpoint = require(cfg, "endpoint", label="资源 Endpoint").rstrip("/")
    deployment = require(cfg, "deployment", label="部署名")
    version = require(cfg, "api_version", label="API 版本")
    url = (f"{endpoint}/openai/deployments/{deployment}/embeddings"
           f"?api-version={version}")
    headers = {"api-key": cfg.get("api_key") or ""}
    body = {"input": texts}
    data = http_json(url, body, headers=headers, timeout=timeout)
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ProviderCallError("响应里没有 data 数组", detail=str(data)[:300])
    return [[float(x) for x in row.get("embedding", [])] for row in rows
            if isinstance(row, dict)]


# --------------------------------------------------------------------------- #
# Cohere（input_type 必填，v1 / v2 响应结构不同）
# --------------------------------------------------------------------------- #
def _cohere(cfg: Dict[str, Any], texts: List[str], input_type: str,
            timeout: float) -> List[List[float]]:
    base = require(cfg, "base_url", label="Base URL")
    model = require(cfg, "model", label="模型名")
    url = join_url(base, "embed")
    headers = {"Authorization": f"Bearer {require(cfg, 'api_key', label='API Key')}"}
    cohere_type = "search_query" if input_type == "query" else "search_document"
    body = {"model": model, "texts": texts, "input_type": cohere_type}
    data = http_json(url, body, headers=headers, timeout=timeout)

    raw = data.get("embeddings") if isinstance(data, dict) else None
    # v2 返回 {"embeddings": {"float": [[...]]}}，v1 返回 {"embeddings": [[...]]}
    if isinstance(raw, dict):
        raw = raw.get("float") or raw.get("int8") or []
    if not isinstance(raw, list):
        raise ProviderCallError("响应里没有 embeddings", detail=str(data)[:300])
    return [[float(x) for x in v] for v in raw]


# --------------------------------------------------------------------------- #
# Jina（openai 路径 + task 字段）
# --------------------------------------------------------------------------- #
def _jina(cfg: Dict[str, Any], texts: List[str], input_type: str,
          timeout: float) -> List[List[float]]:
    base = require(cfg, "base_url", label="Base URL")
    model = require(cfg, "model", label="模型名")
    url = join_url(base, "embeddings")
    headers = {"Authorization": f"Bearer {require(cfg, 'api_key', label='API Key')}"}
    task = "retrieval.query" if input_type == "query" else "retrieval.passage"
    body = {"model": model, "input": texts, "task": task}
    data = http_json(url, body, headers=headers, timeout=timeout)
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ProviderCallError("响应里没有 data 数组", detail=str(data)[:300])
    out = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("embedding"), list):
            out.append([float(x) for x in row["embedding"]])
    return out


# --------------------------------------------------------------------------- #
# Voyage AI
# --------------------------------------------------------------------------- #
def _voyage(cfg: Dict[str, Any], texts: List[str], input_type: str,
            timeout: float) -> List[List[float]]:
    base = require(cfg, "base_url", label="Base URL")
    model = require(cfg, "model", label="模型名")
    url = join_url(base, "embeddings")
    headers = {"Authorization": f"Bearer {require(cfg, 'api_key', label='API Key')}"}
    body = {
        "model": model,
        "input": texts,
        "input_type": "query" if input_type == "query" else "document",
    }
    data = http_json(url, body, headers=headers, timeout=timeout)
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ProviderCallError("响应里没有 data 数组", detail=str(data)[:300])
    return [[float(x) for x in row.get("embedding", [])] for row in rows
            if isinstance(row, dict)]


# --------------------------------------------------------------------------- #
# 阿里云 DashScope 原生（非兼容模式）
# --------------------------------------------------------------------------- #
def _dashscope(cfg: Dict[str, Any], texts: List[str], input_type: str,
               timeout: float) -> List[List[float]]:
    base = (require(cfg, "base_url", label="Base URL")).rstrip("/")
    # 允许用户填成兼容模式地址，这里自动换算成原生路径
    if "/compatible-mode" in base:
        base = base.split("/compatible-mode")[0] + "/api/v1"
    url = join_url(base, "services/embeddings/text-embedding/text-embedding")
    model = require(cfg, "model", label="模型名")
    headers = {"Authorization": f"Bearer {require(cfg, 'api_key', label='API Key')}"}
    body = {
        "model": model,
        "input": {"texts": texts},
        "parameters": {"text_type": "query" if input_type == "query" else "document"},
    }
    data = http_json(url, body, headers=headers, timeout=timeout)
    if isinstance(data, dict) and data.get("code"):
        raise ProviderCallError(f"DashScope 返回错误：{data.get('code')}",
                                detail=str(data.get("message", ""))[:300])
    rows = ((data or {}).get("output") or {}).get("embeddings") or []
    indexed = []
    for i, row in enumerate(rows):
        if isinstance(row, dict) and isinstance(row.get("embedding"), list):
            indexed.append((as_int(row.get("text_index"), i),
                            [float(x) for x in row["embedding"]]))
    indexed.sort(key=lambda x: x[0])
    return [v for _, v in indexed]


# --------------------------------------------------------------------------- #
# Ollama 原生（/api/embed，老版本回退 /api/embeddings）
# --------------------------------------------------------------------------- #
def _ollama(cfg: Dict[str, Any], texts: List[str], input_type: str,
            timeout: float) -> List[List[float]]:
    base = require(cfg, "base_url", label="服务地址").rstrip("/")
    model = require(cfg, "model", label="模型名")
    url = join_url(base, "api/embed")
    body = {"model": model, "input": texts}
    try:
        data = http_json(url, body, timeout=timeout)
    except ProviderCallError as exc:
        if exc.status != 404:
            raise
        # 老版本 Ollama 只支持 /api/embeddings + 单条 prompt
        out = []
        for text in texts:
            one = http_json(join_url(base, "api/embeddings"),
                            {"model": model, "prompt": text}, timeout=timeout)
            vec = one.get("embedding") if isinstance(one, dict) else None
            if isinstance(vec, list):
                out.append([float(x) for x in vec])
        return out

    vectors = data.get("embeddings") if isinstance(data, dict) else None
    if isinstance(vectors, list):
        return [[float(x) for x in v] for v in vectors]
    # 极老版本返回单个 embedding
    single = data.get("embedding") if isinstance(data, dict) else None
    if isinstance(single, list):
        return [[float(x) for x in single]]
    raise ProviderCallError("Ollama 响应里没有 embeddings", detail=str(data)[:300])


# --------------------------------------------------------------------------- #
# HuggingFace TEI（/embed，字段叫 inputs）
# --------------------------------------------------------------------------- #
def _tei(cfg: Dict[str, Any], texts: List[str], input_type: str,
         timeout: float) -> List[List[float]]:
    base = require(cfg, "base_url", label="服务地址").rstrip("/")
    url = join_url(base, "embed")
    headers: Dict[str, str] = {}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    data = http_json(url, {"inputs": texts}, headers=headers, timeout=timeout)
    if isinstance(data, list):
        return [[float(x) for x in v] for v in data if isinstance(v, list)]
    raise ProviderCallError("TEI 响应格式不符合预期", detail=str(data)[:300])


# --------------------------------------------------------------------------- #
# 进程内：FastEmbed
# --------------------------------------------------------------------------- #
def _fastembed(cfg: Dict[str, Any], texts: List[str], input_type: str,
               timeout: float) -> List[List[float]]:
    TextEmbedding = lazy_import("fastembed", "fastembed", attr="TextEmbedding")
    model_name = require(cfg, "model", label="模型名")
    cache_key = f"fastembed:{model_name}:{cfg.get('cache_dir', '')}"
    model = _MODEL_CACHE.get(cache_key)
    if model is None:
        kwargs: Dict[str, Any] = {"model_name": model_name}
        if cfg.get("cache_dir"):
            kwargs["cache_dir"] = cfg["cache_dir"]
        threads = as_int(cfg.get("threads"), 0)
        if threads > 0:
            kwargs["threads"] = threads
        model = TextEmbedding(**kwargs)
        _MODEL_CACHE[cache_key] = model
    return [list(map(float, vec)) for vec in model.embed(texts)]


# --------------------------------------------------------------------------- #
# 进程内：sentence-transformers
# --------------------------------------------------------------------------- #
def _sentence_transformers(cfg: Dict[str, Any], texts: List[str], input_type: str,
                           timeout: float) -> List[List[float]]:
    ST = lazy_import("sentence_transformers", "sentence-transformers",
                     attr="SentenceTransformer")
    model_name = require(cfg, "model", label="HF 模型名")
    device = (cfg.get("device") or "cpu").strip()
    cache_key = f"st:{model_name}:{device}"
    model = _MODEL_CACHE.get(cache_key)
    if model is None:
        kwargs: Dict[str, Any] = {"device": device}
        if cfg.get("cache_dir"):
            kwargs["cache_dir"] = cfg["cache_dir"]
        model = ST(model_name, **kwargs)
        _MODEL_CACHE[cache_key] = model
    normalize = str(cfg.get("normalize", "true")).lower() != "false"
    # 部分中文模型（bge / e5）检索时查询要加前缀，这里只在 query 侧补
    query_prefix = cfg.get("query_prefix") or ""
    payload = [f"{query_prefix}{t}" if input_type == "query" else t for t in texts]
    vectors = model.encode(payload, normalize_embeddings=normalize)
    return [list(map(float, vec)) for vec in vectors]


_HANDLERS = {
    "openai": _openai,
    "azure": _azure,
    "cohere": _cohere,
    "jina": _jina,
    "voyage": _voyage,
    "dashscope": _dashscope,
    "ollama": _ollama,
    "tei": _tei,
    "fastembed": _fastembed,
    "sentence_transformers": _sentence_transformers,
}


def supported_protocols() -> List[str]:
    return sorted(_HANDLERS)
