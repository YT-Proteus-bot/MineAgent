"""重排模型（rerank）枚举清单。

重排和向量模型是两件事：向量模型负责「把文本放进同一个空间里找近似」，
重排模型负责「拿到候选后，逐条判断它到底能不能回答问题」。前者决定召回，
后者决定精度，所以单独做成一类 provider。

真实世界里 rerank 也只有少数几种「协议」：
- openai_rerank：POST {base}/rerank，{model, query, documents, top_n} → results[]
  （Jina / 硅基流动 / vLLM / Xinference / 各家网关都是这个形状）
- cohere / voyage / dashscope / tei：字段名各不相同，各自一套（见 rerank.py）

新增一家厂商 = 加一个 entry；协议已有就不用写代码。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .catalog_common import F, models

# 大多数云端 rerank 共用的字段
BASE = [
    F("base_url", "Base URL", required=True, placeholder="https://api.example.com/v1",
      help_text="兼容 OpenAI 风格时通常要带 /v1"),
    F("model", "模型名", required=True, placeholder="rerank-v3.5"),
    F("top_n", "默认返回条数", kind="number", default=3,
      help_text="节点没单独指定时，重排后保留几条"),
    F("max_docs", "单次最多送检条数", kind="number", default=50,
      help_text="候选太多时先截断，省 token 也避开服务商的条数上限"),
    F("api_key", "API Key", secret=True, placeholder="sk-..."),
]

RERANK: List[Dict[str, Any]] = [
    # ------------------------------------------------------------------ 云端
    {
        "id": "cohere", "label": "Cohere Rerank", "group": "cloud", "protocol": "cohere",
        "base_url": "https://api.cohere.com/v2", "fields": BASE,
        "models": models("rerank-v3.5, rerank-multilingual-v3.0"),
        "help": "重排领域的老牌服务；走 /v2/rerank，返回 results[].relevance_score。",
    },
    {
        "id": "jina", "label": "Jina Reranker", "group": "cloud", "protocol": "openai_rerank",
        "base_url": "https://api.jina.ai/v1", "fields": BASE,
        "models": models("jina-reranker-v2-base-multilingual, jina-reranker-m0,"
                         " jina-reranker-v3"),
        "help": "多语言效果好；/v1/rerank 与 OpenAI 风格一致。",
    },
    {
        "id": "siliconflow", "label": "硅基流动 SiliconFlow", "group": "cloud",
        "protocol": "openai_rerank", "base_url": "https://api.siliconflow.cn/v1",
        "fields": BASE,
        "models": models("BAAI/bge-reranker-v2-m3, BAAI/bge-reranker-base,"
                         " Qwen/Qwen3-Reranker-8B"),
        "help": "国内 bge-reranker 最省事的一家，和向量模型可以共用同一个 key。",
    },
    {
        "id": "dashscope", "label": "阿里云百炼 / 通义", "group": "cloud",
        "protocol": "dashscope", "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "fields": [
            F("base_url", "Base URL", required=True,
              placeholder="https://dashscope.aliyuncs.com/api/v1",
              help_text="填兼容模式地址也会自动换算成原生路径"),
            F("model", "模型名", required=True, placeholder="gte-rerank-v2"),
            F("top_n", "默认返回条数", kind="number", default=3),
            F("max_docs", "单次最多送检条数", kind="number", default=50),
            F("api_key", "API Key", secret=True, placeholder="sk-..."),
        ],
        "models": models("gte-rerank-v2, gte-rerank"),
        "help": "走百炼原生的 text-rerank 接口，input.query / input.documents。",
    },
    {
        "id": "voyage", "label": "Voyage AI", "group": "cloud", "protocol": "voyage",
        "base_url": "https://api.voyageai.com/v1", "fields": BASE,
        "models": models("rerank-2.5, rerank-2.5-lite, rerank-2"),
        "help": "检索质量口碑好；返回 data[].relevance_score。",
    },

    # ------------------------------------------------------ 开源自部署 / 本地
    {
        "id": "tei", "label": "HuggingFace TEI", "group": "local", "protocol": "tei",
        "base_url": "http://127.0.0.1:8080", "key_required": False,
        "fields": [
            F("base_url", "服务地址", required=True, placeholder="http://127.0.0.1:8080"),
            F("model", "模型名（可留空）", placeholder="BAAI/bge-reranker-v2-m3",
              help_text="TEI 按部署时加载的模型推理，这里只是备注"),
            F("top_n", "默认返回条数", kind="number", default=3),
            F("max_docs", "单次最多送检条数", kind="number", default=50),
            F("api_key", "访问令牌", secret=True, placeholder="可选"),
        ],
        "models": models("BAAI/bge-reranker-v2-m3, BAAI/bge-reranker-large"),
        "help": "Text Embeddings Inference 的 /rerank，本地离线首选。",
    },
    {
        "id": "vllm", "label": "vLLM", "group": "local", "protocol": "openai_rerank",
        "base_url": "http://127.0.0.1:8000/v1", "key_required": False,
        "fields": BASE,
        "models": models("BAAI/bge-reranker-v2-m3, jinaai/jina-reranker-v2-base-multilingual"),
        "help": "vLLM 的 /v1/rerank 与 Jina 协议一致，显存够就能自己托管重排。",
    },
    {
        "id": "xinference", "label": "Xinference", "group": "local", "protocol": "openai_rerank",
        "base_url": "http://127.0.0.1:9997/v1", "key_required": False,
        "fields": BASE,
        "models": models("bge-reranker-v2-m3, jina-reranker-v2"),
        "help": "部署 rerank 模型后，接口形状和 OpenAI 兼容网关一致。",
    },

    # ------------------------------------------------------------ 通用兜底
    {
        "id": "openai_compatible", "label": "任意 OpenAI 兼容端点", "group": "cloud",
        "protocol": "openai_rerank", "base_url": "", "fields": BASE,
        "models": models(""),
        "help": "只要对方实现 POST /v1/rerank，返回 results[].relevance_score（或 score）"
                "就能接进来；自建网关、公司内网网关填这里。",
    },
]


PROTOCOL_LABELS = {
    "openai_rerank": "OpenAI 风格 /rerank",
    "cohere": "Cohere /v2/rerank",
    "voyage": "Voyage AI /rerank",
    "dashscope": "阿里云原生 text-rerank",
    "tei": "HuggingFace TEI /rerank",
}
