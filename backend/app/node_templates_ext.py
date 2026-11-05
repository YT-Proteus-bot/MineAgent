"""细粒度节点模板（第二批）。

相对第一批，这一批把 Agent 内部常见的处理环节全部拆成独立、可代码编辑的节点：
意图理解 → 查询改写 → 检索（向量/关键词/混合）→ 重排 → 上下文拼装 → 引用，
以及文档解析、数据存储、文本加工、可靠性控制等。

每个模板都只用 runtime_sdk 里真实存在的能力；缺可选依赖时会给出可执行的提示，
而不是直接崩掉。
"""
from __future__ import annotations

E = {}

# --------------------------------------------------------------------------- #
# 意图与查询理解
# --------------------------------------------------------------------------- #
E["intent_recognizer"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """意图识别：把用户输入归到预定义意图，并给出置信度。"""
    intents = ctx.params.get("intents") or ["咨询", "任务执行", "闲聊", "投诉", "其他"]
    data = ctx.json_prompt(
        "判断用户这句话属于哪个意图，并给出置信度。",
        schema={"intent": "", "confidence": 0.0, "reason": ""},
        context=f"可选意图：{intents}\\n用户输入：{ctx.text}",
    )
    ctx.state["intent"] = data.get("intent") if isinstance(data, dict) else ""
    ctx.emit("intent", data)
    return data
'''

E["slot_filler"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """槽位抽取：按 schema 从输入里抽结构化字段，缺失留空。"""
    schema = ctx.params.get("schema") or {"who": "", "what": "", "when": "", "where": ""}
    data = ctx.json_prompt("从输入中抽取槽位，抽不到就留空字符串。", schema=schema, context=ctx.text)
    ctx.state["slots"] = data
    return data
'''

E["query_rewrite"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """查询改写：把口语化问题改写成适合检索的查询。"""
    return ctx.llm(
        f"把下面这句话改写成 1 条用于检索的简洁查询，只输出查询本身：\\n{ctx.text}",
        system="你是检索查询改写器，只输出改写结果，不加解释。",
    )
'''

E["query_expand"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """查询扩展：生成多条同义查询，提升召回。"""
    n = ctx.params.get("n", 3)
    data = ctx.json_prompt(
        f"围绕用户问题生成 {n} 条不同角度的同义检索查询。",
        schema={"queries": ["..."]},
        context=ctx.text,
    )
    queries = list(ctx.input) if isinstance(ctx.input, list) else []
    if isinstance(data, dict) and isinstance(data.get("queries"), list):
        queries = [ctx.text] + data["queries"]
    return queries
'''

E["query_router"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """查询路由：判断该问题去哪个知识库 / 哪条链路。"""
    stores = ctx.params.get("stores") or ["docs", "faq", "manual"]
    pick = ctx.llm(
        f"用户问题：{ctx.text}\\n可选知识库：{stores}\\n只回答其中一个库名，不要解释。",
        system="你只输出一个库名。",
    ).strip()
    if pick not in stores:
        pick = stores[0]
    ctx.state["route_store"] = pick
    ctx.emit("route_store", {"store": pick})
    return pick
'''

# --------------------------------------------------------------------------- #
# RAG 工程
# --------------------------------------------------------------------------- #
E["doc_loader"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """文档加载：把 pdf / docx / md / txt / csv 抽成纯文本。"""
    path = ctx.params.get("path") or ctx.text.strip()
    if not path:
        raise ValueError("doc_loader 需要指定文件路径（可写在参数 path 里）")
    return ctx.load_document(path)
'''

E["text_splitter"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """文本切分：按段落 + 长度切块，带重叠。"""
    size = int(ctx.params.get("chunk_size", 600))
    overlap = int(ctx.params.get("overlap", 80))
    chunks = ctx.split_text(ctx.text, size, overlap)
    ctx.emit("chunks", {"count": len(chunks), "size": size})
    return chunks
'''

E["chunk_refiner"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """分块精炼：给每个 chunk 补一句语义标题，方便后续召回与展示。"""
    chunks = ctx.input if isinstance(ctx.input, list) else ctx.split_text(ctx.text, 600, 80)
    out = []
    for chunk in chunks[:20]:
        text = chunk if isinstance(chunk, str) else str(chunk)
        refined = ctx.llm(
            f"先给这段内容起一个 15 字以内的标题，再原样输出正文，用「||」分隔：\\n{text}",
            system="只输出「标题||正文」，不要别的内容。",
        )
        out.append({"title": refined.split("||")[0].strip(), "text": text})
    return out
'''

E["vector_indexer"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """向量入库：把文本块写进项目内的向量库。"""
    chunks = ctx.input if isinstance(ctx.input, list) else [ctx.text]
    count = 0
    for chunk in chunks:
        text = chunk if isinstance(chunk, str) else str(chunk)
        if text.strip():
            ctx.vector_upsert(text)
            count += 1
    ctx.emit("indexed", {"count": count})
    return {"indexed": count}
'''

E["hybrid_retriever"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """混合检索：向量库召回 + 文件关键词召回各取一份。"""
    top_k = int(ctx.params.get("top_k", 4))
    query = ctx.state.get("query") or ctx.text
    vec = ctx.vector_search(query, top_k=top_k)
    kw = ctx.retrieve(query, top_k=top_k, mode="keyword")
    ctx.emit("hybrid", {"vector": len(vec), "keyword": len(kw)})
    return {"query": query, "vector": vec, "keyword": kw}
'''

E["bm25_search"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """关键词检索：基于词频与 IDF 的传统检索。"""
    return ctx.retrieve(ctx.text, top_k=int(ctx.params.get("top_k", 6)), mode="keyword")
'''

E["reranker"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """重排：让模型给候选片段逐个打相关性分，取前 K。"""
    docs = ctx.input if isinstance(ctx.input, list) else [ctx.text]
    query = ctx.state.get("query") or ctx.text
    return ctx.rerank(query, docs, top_k=int(ctx.params.get("top_k", 3)))
'''

E["context_builder"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """上下文拼装：把检索结果压成带编号的参考上下文。"""
    docs = ctx.input if isinstance(ctx.input, list) else [ctx.text]
    context = ctx.build_context(docs, max_chars=int(ctx.params.get("max_chars", 3000)))
    ctx.state["context"] = context
    return context
'''

E["citation_formatter"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """引用标注：给答案补上 [1][2] 形式的来源编号。"""
    return ctx.llm(
        f"给下面这段回答标注引用编号，只能使用参考材料里出现过的编号：\\n{ctx.text}",
        system="只输出标注后的回答正文。",
    )
'''

E["doc_grader"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """文档相关性打分：判断召回内容是否真的能回答问题。"""
    return ctx.json_prompt(
        "给每段材料与问题的相关性打 0-1 分，并给出是否需要重新检索。",
        schema={"docs": [{"id": "", "score": 0.0}], "need_more": False},
        context=ctx.input if ctx.input else ctx.text,
    )
'''

E["rag_evaluator"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """RAG 质量评估：答案是否被检索内容支撑、是否答到点上。"""
    return ctx.json_prompt(
        "评估这组「问题-检索内容-答案」的质量。",
        schema={"faithfulness": 0.0, "relevance": 0.0, "issues": ["..."]},
        context=ctx.input if ctx.input else ctx.text,
    )
'''

# --------------------------------------------------------------------------- #
# 数据与存储
# --------------------------------------------------------------------------- #
E["db_write"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """数据写入：执行 INSERT / UPDATE / DELETE（只允许显式开启）。"""
    sql = ctx.params.get("sql") or ""
    if not sql:
        raise ValueError("db_write 需要在参数 sql 里填写写语句")
    if not ctx.params.get("allow", False):
        raise PermissionError("写操作默认禁用，请把参数 allow 设为 true")
    return ctx.exec_sql(sql, readonly=False)
'''

E["kv_store"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """KV 存储：键值读写，适合存中间结果与状态。"""
    key = ctx.params.get("key") or "default"
    if (ctx.params.get("action") or "get") == "set":
        ctx.kv_set(key, ctx.text)
        return {"key": key, "value": ctx.text}
    return {"key": key, "value": ctx.kv_get(key) or ""}
'''

E["cache_lookup"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """缓存查询：命中就返回缓存值，供下游决定是否跳过重算。"""
    key = ctx.cache_key(ctx.text)
    value = ctx.cache_get(key)
    ctx.emit("cache", {"key": key, "hit": value is not None})
    return {"hit": value is not None, "value": value or ""}
'''

E["cache_write"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """缓存写入：把当前结果按输入做键存进缓存。"""
    key = ctx.cache_key(ctx.params.get("key") or ctx.node_name)
    ctx.cache_set(key, ctx.text, ttl=int(ctx.params.get("ttl", 3600)))
    return ctx.text
'''

E["graph_query"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """图查询：在项目内的三元组表里按关键词找关系。"""
    return ctx.graph_query(ctx.text, limit=int(ctx.params.get("limit", 20)))
'''

# --------------------------------------------------------------------------- #
# 文档与多模态
# --------------------------------------------------------------------------- #
E["ocr_extract"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """OCR：从图片里抽文字（需要 paddleocr 或 pytesseract）。"""
    path = ctx.params.get("path") or ctx.text.strip()
    return ctx.ocr_text(path)
'''

E["pdf_parser"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """PDF 解析：抽出正文与页数（需要 pypdf）。"""
    path = ctx.params.get("path") or ctx.text.strip()
    return ctx.load_document(path)
'''

E["table_parser"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """表格解析：把 CSV / Markdown 表格转成结构化行。"""
    return ctx.parse_table(ctx.text)
'''

E["image_analyzer"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """图像理解：描述图片内容（需要配置多模态模型）。"""
    path = ctx.params.get("path") or ctx.text.strip()
    return ctx.describe_image(path)
'''

E["speech_to_text"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """语音转写：把音频转成文字（需要 faster-whisper）。"""
    path = ctx.params.get("path") or ctx.text.strip()
    return ctx.transcribe(path)
'''

# --------------------------------------------------------------------------- #
# 文本加工
# --------------------------------------------------------------------------- #
E["translator"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """翻译：指定目标语言。"""
    target = ctx.params.get("target") or "English"
    return ctx.llm(f"把下面内容翻译成{target}，只输出译文：\\n{ctx.text}")
'''

E["classifier"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """分类器：把输入归到给定标签之一。"""
    labels = ctx.params.get("labels") or ["咨询", "投诉", "其他"]
    return ctx.json_prompt(
        "把输入归到给定标签之一。",
        schema={"label": "", "confidence": 0.0, "reason": ""},
        context=f"可选标签：{labels}\\n内容：{ctx.text}",
    )
'''

E["extractor"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """实体抽取：人名 / 机构 / 地点 / 金额 / 时间。"""
    return ctx.json_prompt(
        "抽取文本中的实体，抽不到就给空数组。",
        schema={"persons": [], "orgs": [], "locations": [], "amounts": [], "times": []},
        context=ctx.text,
    )
'''

E["sentiment"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """情感分析：正向 / 中性 / 负向 + 强度。"""
    return ctx.json_prompt(
        "判断情感倾向。",
        schema={"sentiment": "positive|neutral|negative", "score": 0.0, "reason": ""},
        context=ctx.text,
    )
'''

E["fact_checker"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """事实核查：逐条判断陈述是否被支撑。"""
    return ctx.json_prompt(
        "把文本拆成事实性陈述，逐条判断能否被支撑。",
        schema={"claims": [{"text": "", "verdict": "supported|unclear|contradicted"}],
                "summary": ""},
        context=ctx.text,
    )
'''

E["deduplicator"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """去重：按内容前 120 字符归并重复项。"""
    items = ctx.input if isinstance(ctx.input, list) else ctx.text.split("\\n")
    seen, out = set(), []
    for item in items:
        key = str(item).strip().lower()[:120]
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    ctx.emit("dedup", {"before": len(items), "after": len(out)})
    return out
'''

E["merger"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """合并：把多路结果按顺序拼成一段。"""
    items = ctx.input if isinstance(ctx.input, list) else [ctx.text]
    sep = ctx.params.get("separator") or "\\n\\n"
    return sep.join(str(i) for i in items)
'''

E["outline_builder"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """大纲生成：给主题产出一份三级 Markdown 大纲。"""
    depth = int(ctx.params.get("depth", 3))
    return ctx.llm(
        f"为下面的主题写一份 {depth} 级 Markdown 大纲，只输出大纲：\\n{ctx.text}",
        system="你只输出 Markdown 大纲。",
    )
'''

E["section_writer"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """分段写作：按给定小标题写一节正文。"""
    words = int(ctx.params.get("words", 400))
    return ctx.llm(
        f"按下面的标题写一节内容，约 {words} 字，只输出正文：\\n{ctx.text}",
        system="只输出这一节的正文。",
    )
'''

E["polisher"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """润色：保持原意，改掉啰嗦与病句。"""
    style = ctx.params.get("style") or "简洁专业"
    return ctx.llm(
        f"润色下面这段文字（风格：{style}），只输出润色后的正文：\\n{ctx.text}"
    )
'''

E["title_generator"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """标题生成：给内容起若干候选标题。"""
    n = int(ctx.params.get("n", 5))
    return ctx.json_prompt(
        f"为这段内容生成 {n} 个候选标题，长短各一些。",
        schema={"titles": ["..."]},
        context=ctx.text,
    )
'''

# --------------------------------------------------------------------------- #
# 可靠性控制
# --------------------------------------------------------------------------- #
E["rate_limiter"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """限流：控制每分钟调用次数，超了就等一下。"""
    ctx.wait_for_slot(int(ctx.params.get("per_minute", 30)))
    return ctx.text
'''

E["circuit_breaker"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """熔断：连续失败达到阈值就快速失败，避免拖垮上游。"""
    threshold = int(ctx.params.get("threshold", 3))
    fails = int(ctx.state.get("breaker_fails", 0))
    if fails >= threshold:
        raise RuntimeError(f"熔断已打开（连续失败 {fails} 次），本轮直接跳过")
    ctx.state["breaker_fails"] = 0
    return ctx.text
'''

E["budget_guard"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """预算控制：token 用量超限就停下来。"""
    limit = int(ctx.params.get("max_tokens", 50000))
    used = int(ctx.state.get("tokens_used", 0))
    ctx.emit("budget", {"used": used, "limit": limit})
    if used > limit:
        raise RuntimeError(f"token 预算超限：{used} / {limit}")
    return ctx.text
'''

E["cost_tracker"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """成本统计：按 token 用量估算花费。"""
    used = int(ctx.state.get("tokens_used", 0))
    price = float(ctx.params.get("price_per_k", 0.002))
    cost = round(used / 1000.0 * price, 6)
    ctx.emit("cost", {"tokens": used, "cost_usd": cost})
    return {"tokens": used, "cost_usd": cost}
'''

# --------------------------------------------------------------------------- #
# 输出处理
# --------------------------------------------------------------------------- #
E["json_repair"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """JSON 修复：把模型输出里夹带的 JSON 抽出来并解析。"""
    data = ctx.parse_json(ctx.text)
    if data is None:
        data = ctx.json_prompt("把下面内容整理成合法 JSON，字段尽量保留原意。",
                               schema={"data": {}}, context=ctx.text)
    return data
'''

E["markdown_render"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Markdown 渲染：把纯文本包装成规范的 Markdown。"""
    text = ctx.text.strip()
    title = ctx.params.get("title") or ""
    if text.startswith("#") or "\\n#" in text:
        return text
    head = f"# {title}\\n\\n" if title else ""
    return head + text
'''

EXT_TEMPLATES = E
