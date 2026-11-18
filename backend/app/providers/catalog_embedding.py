"""向量模型（embedding）枚举清单。

真实世界里 embedding 只有少数几种「协议」，几十家厂商都是 OpenAI 兼容的
/v1/embeddings。所以这里枚举的是【厂商 + 模型 + 默认地址 + 协议】，
协议实现只需要几套（见 embedding.py）。新增一家厂商 = 加一个 entry。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .catalog_common import BASE_EMBEDDING_FIELDS as BASE, F, models

# 云端厂商默认字段就是 BASE，这里起个短名字方便阅读
EMB: List[Dict[str, Any]] = [
    # ------------------------------------------------------------------ 云端
    {
        "id": "openai", "label": "OpenAI", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.openai.com/v1", "fields": BASE,
        "models": models("text-embedding-3-small:1536, text-embedding-3-large:3072,"
                         " text-embedding-ada-002:1536"),
        "help": "OpenAI 官方，text-embedding-3 系列支持 dimensions 参数动态降维。",
    },
    {
        "id": "azure_openai", "label": "Azure OpenAI", "group": "cloud", "protocol": "azure",
        "base_url": "", "key_required": True,
        "fields": [
            F("endpoint", "资源 Endpoint", required=True,
              placeholder="https://xxx.openai.azure.com"),
            F("deployment", "部署名", required=True, placeholder="text-embedding-3-small"),
            F("api_version", "API 版本", required=True, placeholder="2024-02-01"),
            F("model", "模型名", required=True, placeholder="text-embedding-3-small"),
            F("dim", "向量维度", kind="number", default=0),
            F("api_key", "API Key", secret=True, required=True),
        ],
        "models": models("text-embedding-3-small:1536, text-embedding-3-large:3072,"
                         " text-embedding-ada-002:1536"),
        "help": "Azure 的路径是 /openai/deployments/<部署名>/embeddings?api-version=…，"
                "和官方 OpenAI 不同，所以单独走 azure 协议。",
    },
    {
        "id": "dashscope", "label": "阿里云百炼 / 通义", "group": "cloud",
        "protocol": "dashscope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "fields": BASE,
        "models": models("text-embedding-v4:1024, text-embedding-v3:1024,"
                         " text-embedding-v2:1536, text-embedding-v1:1536"),
        "help": "默认走百炼的 OpenAI 兼容模式；也可在 Protocol 里改成原生 dashscope 协议。",
    },
    {
        "id": "zhipu", "label": "智谱 GLM", "group": "cloud", "protocol": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4", "fields": BASE,
        "models": models("embedding-3:2048, embedding-2:1024"),
    },
    {
        "id": "siliconflow", "label": "硅基流动 SiliconFlow", "group": "cloud",
        "protocol": "openai", "base_url": "https://api.siliconflow.cn/v1", "fields": BASE,
        "models": models("BAAI/bge-m3:1024, Qwen/Qwen3-Embedding-8B:4096,"
                         " Qwen/Qwen3-Embedding-4B:2560, BAAI/bge-large-zh-v1.5:1024,"
                         " netease-youdao/bce-embedding-base_v1:768"),
        "help": "国内用 bge-m3 / Qwen3-Embedding 最省事的一家，中文效果稳定。",
    },
    {
        "id": "volcengine", "label": "火山方舟（豆包）", "group": "cloud", "protocol": "openai",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3", "fields": BASE,
        "models": models("doubao-embedding:2048, doubao-embedding-large:2048"),
    },
    {
        "id": "hunyuan", "label": "腾讯混元", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1", "fields": BASE,
        "models": models("hunyuan-embedding:1024"),
    },
    {
        "id": "qianfan", "label": "百度千帆", "group": "cloud", "protocol": "openai",
        "base_url": "https://qianfan.baidubce.com/v2", "fields": BASE,
        "models": models("embedding-v1:384, tao-8k:1024, bge-large-zh:1024"),
    },
    {
        "id": "baichuan", "label": "百川智能", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.baichuan-ai.com/v1", "fields": BASE,
        "models": models("Baichuan-Text-Embedding:1024"),
    },
    {
        "id": "minimax", "label": "MiniMax", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.minimax.chat/v1", "fields": BASE,
        "models": models("embo-01:1536"),
    },
    {
        "id": "xfyun", "label": "讯飞星火", "group": "cloud", "protocol": "openai",
        "base_url": "https://spark-api-open.xf-yun.com/v1", "fields": BASE,
        "models": models("embedding:0"),
        "help": "讯飞的向量化接口对鉴权有额外要求，若直连失败建议改用其 OpenAI 兼容网关。",
    },
    {
        "id": "moonshot", "label": "月之暗面 Kimi", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.moonshot.cn/v1", "fields": BASE,
        "models": models(""),
        "help": "Kimi 目前没有公开的 embedding 接口，模型名需要你填服务端实际支持的。",
    },
    {
        "id": "mistral", "label": "Mistral AI", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.mistral.ai/v1", "fields": BASE,
        "models": models("mistral-embed:1024, codestral-embed:1536"),
    },
    {
        "id": "cohere", "label": "Cohere", "group": "cloud", "protocol": "cohere",
        "base_url": "https://api.cohere.com/v1", "fields": BASE,
        "models": models("embed-v4.0:1536, embed-multilingual-v3.0:1024,"
                         " embed-english-v3.0:1024"),
        "help": "Cohere 用 input_type 区分文档和查询，协议不同，已单独实现。",
    },
    {
        "id": "jina", "label": "Jina AI", "group": "cloud", "protocol": "jina",
        "base_url": "https://api.jina.ai/v1", "fields": BASE,
        "models": models("jina-embeddings-v4:2048, jina-embeddings-v3:1024,"
                         " jina-clip-v2:1024"),
        "help": "Jina 用 task 字段区分任务，已单独实现。",
    },
    {
        "id": "voyage", "label": "Voyage AI", "group": "cloud", "protocol": "voyage",
        "base_url": "https://api.voyageai.com/v1", "fields": BASE,
        "models": models("voyage-3-large:1024, voyage-3:1024, voyage-3-lite:512,"
                         " voyage-code-3:1024"),
        "help": "检索质量口碑很好，Anthropic 官方推荐搭配。",
    },
    {
        "id": "gemini", "label": "Google Gemini", "group": "cloud", "protocol": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "fields": BASE,
        "models": models("gemini-embedding-001:3072, text-embedding-004:768"),
    },
    {
        "id": "together", "label": "Together AI", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.together.xyz/v1", "fields": BASE,
        "models": models("BAAI/bge-large-en-v1.5:1024, togethercomputer/m2-bert-80M-32k-retrieval:768"),
    },
    {
        "id": "fireworks", "label": "Fireworks AI", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.fireworks.ai/inference/v1", "fields": BASE,
        "models": models("nomic-ai/nomic-embed-text-v1.5:768"),
    },
    {
        "id": "deepinfra", "label": "DeepInfra", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.deepinfra.com/v1/openai", "fields": BASE,
        "models": models("BAAI/bge-m3:1024"),
    },
    {
        "id": "nebius", "label": "Nebius", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.studio.nebius.ai/v1", "fields": BASE,
        "models": models("BAAI/bge-en-icl:4096, BAAI/bge-multilingual-gemma2:3584"),
    },
    {
        "id": "openrouter", "label": "OpenRouter", "group": "cloud", "protocol": "openai",
        "base_url": "https://openrouter.ai/api/v1", "fields": BASE,
        "models": models(""),
        "help": "OpenRouter 主要转发对话模型，embedding 支持依上游而定。",
    },
    {
        "id": "nomic", "label": "Nomic", "group": "cloud", "protocol": "openai",
        "base_url": "https://api-atlas.nomic.ai/v1", "fields": BASE,
        "models": models("nomic-embed-text-v1.5:768, nomic-embed-text-v2-moe:768"),
    },
    {
        "id": "mixedbread", "label": "Mixedbread", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.mixedbread.ai/v1", "fields": BASE,
        "models": models("mxbai-embed-large-v1:1024, mxbai-embed-2d-large-v1:1024"),
    },
    {
        "id": "upstage", "label": "Upstage", "group": "cloud", "protocol": "openai",
        "base_url": "https://api.upstage.ai/v1/solar", "fields": BASE,
        "models": models("embedding-query:4096, embedding-passage:4096,"
                         " solar-embedding-1-large-passage:4096"),
    },
    {
        "id": "snowflake", "label": "Snowflake", "group": "cloud", "protocol": "openai",
        "base_url": "", "fields": BASE,
        "models": models("snowflake-arctic-embed-l-v2.0:1024"),
        "help": "Cortex 的 embedding 走账号专属地址，Base URL 需自行填写。",
    },
    {
        "id": "vertex", "label": "Google Vertex AI", "group": "cloud", "protocol": "openai",
        "base_url": "", "fields": BASE,
        "models": models("text-embedding-005:768, text-multilingual-embedding-002:768"),
        "help": "需要先用服务账号换取 access token，作为 api_key 填入。",
    },
    {
        "id": "bedrock", "label": "AWS Bedrock", "group": "cloud", "protocol": "openai",
        "base_url": "", "fields": BASE,
        "models": models("amazon.titan-embed-text-v2:1024, cohere.embed-multilingual-v3:1024"),
        "help": "Bedrock 原生需要 SigV4 签名。建议通过 Bedrock 的 OpenAI 兼容网关接入，"
                "或填代理地址。",
    },
    {
        "id": "openai_compatible", "label": "任意 OpenAI 兼容端点", "group": "cloud",
        "protocol": "openai", "base_url": "", "fields": BASE,
        "models": models(""),
        "help": "只要对方实现 POST /v1/embeddings，就能接进来。",
    },

    # ------------------------------------------------------- 本地 / 自部署
    {
        "id": "ollama", "label": "Ollama（本地）", "group": "local", "protocol": "ollama",
        "base_url": "http://127.0.0.1:11434", "key_required": False,
        "fields": [
            F("base_url", "服务地址", required=True, placeholder="http://127.0.0.1:11434",
              help_text="不要带 /v1，Ollama 原生接口用 /api/embed"),
            F("model", "模型名", required=True, placeholder="bge-m3"),
            F("dim", "向量维度", kind="number", default=0),
            F("batch_size", "单次批量", kind="number", default=32),
        ],
        "models": models("nomic-embed-text:768, bge-m3:1024, mxbai-embed-large:1024,"
                         " qwen3-embedding:4096, snowflake-arctic-embed2:1024"),
        "help": "本地离线首选。先 ollama pull 模型，再回来点「连接测试」。",
    },
    {
        "id": "tei", "label": "HuggingFace TEI", "group": "local", "protocol": "tei",
        "base_url": "http://127.0.0.1:8080", "key_required": False,
        "fields": [
            F("base_url", "服务地址", required=True, placeholder="http://127.0.0.1:8080"),
            F("model", "模型名（可留空）", placeholder="BAAI/bge-m3"),
            F("dim", "向量维度", kind="number", default=0),
            F("batch_size", "单次批量", kind="number", default=32),
            F("api_key", "访问令牌", secret=True, placeholder="可选"),
        ],
        "models": models("BAAI/bge-m3:1024, BAAI/bge-large-zh-v1.5:1024"),
        "help": "Text Embeddings Inference，性能好、内存占用低，生产部署推荐。",
    },
    {
        "id": "vllm", "label": "vLLM", "group": "local", "protocol": "openai",
        "base_url": "http://127.0.0.1:8000/v1", "key_required": False, "fields": BASE,
        "models": models("intfloat/e5-mistral-7b-instruct:4096, BAAI/bge-m3:1024"),
    },
    {
        "id": "lmstudio", "label": "LM Studio", "group": "local", "protocol": "openai",
        "base_url": "http://127.0.0.1:1234/v1", "key_required": False, "fields": BASE,
        "models": models("nomic-embed-text-v1.5:768"),
    },
    {
        "id": "xinference", "label": "Xinference", "group": "local", "protocol": "openai",
        "base_url": "http://127.0.0.1:9997/v1", "key_required": False, "fields": BASE,
        "models": models("bge-m3:1024, bge-large-zh-v1.5:1024"),
    },
    {
        "id": "localai", "label": "LocalAI", "group": "local", "protocol": "openai",
        "base_url": "http://127.0.0.1:8080/v1", "key_required": False, "fields": BASE,
        "models": models(""),
    },
    {
        "id": "fastchat", "label": "FastChat", "group": "local", "protocol": "openai",
        "base_url": "http://127.0.0.1:8000/v1", "key_required": False, "fields": BASE,
        "models": models(""),
    },

    # ------------------------------------------------------ 进程内直接推理
    {
        "id": "fastembed", "label": "FastEmbed（进程内）", "group": "inproc", "protocol": "fastembed",
        "base_url": "", "key_required": False, "pip": "fastembed",
        "fields": [
            F("model", "模型名", required=True, placeholder="BAAI/bge-small-zh-v1.5"),
            F("dim", "向量维度", kind="number", default=0),
            F("cache_dir", "模型缓存目录", placeholder="留空用默认缓存"),
            F("threads", "线程数", kind="number", default=0),
        ],
        "models": models("BAAI/bge-small-zh-v1.5:512, BAAI/bge-base-zh-v1.5:768,"
                         " BAAI/bge-m3:1024, nomic-ai/nomic-embed-text-v1.5:768,"
                         " sentence-transformers/all-MiniLM-L6-v2:384"),
        "help": "ONNX 推理，不需要 torch，体积比 sentence-transformers 小很多。首跑会下载模型。",
    },
    {
        "id": "sentence_transformers", "label": "sentence-transformers（进程内）",
        "group": "inproc", "protocol": "sentence_transformers", "base_url": "",
        "key_required": False, "pip": "sentence-transformers",
        "fields": [
            F("model", "HF 模型名或本地路径", required=True,
              placeholder="BAAI/bge-m3"),
            F("dim", "向量维度", kind="number", default=0),
            F("device", "设备", default="cpu", options=["cpu", "cuda", "mps"]),
            F("normalize", "归一化", default="true", options=["true", "false"]),
            F("cache_dir", "模型缓存目录"),
        ],
        "models": models("BAAI/bge-m3:1024, BAAI/bge-large-zh-v1.5:1024,"
                         " intfloat/multilingual-e5-large:1024,"
                         " sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2:384,"
                         " jinaai/jina-embeddings-v2-base-zh:768"),
        "help": "会拉入 torch（安装包约 2GB），首次加载慢。生产环境建议改用 Ollama / TEI。",
    },
]


PROTOCOL_LABELS = {
    "openai": "OpenAI 兼容 /v1/embeddings",
    "azure": "Azure OpenAI",
    "cohere": "Cohere",
    "jina": "Jina",
    "voyage": "Voyage AI",
    "dashscope": "阿里云原生",
    "ollama": "Ollama /api/embed",
    "tei": "HuggingFace TEI",
    "fastembed": "FastEmbed 进程内",
    "sentence_transformers": "sentence-transformers 进程内",
}
