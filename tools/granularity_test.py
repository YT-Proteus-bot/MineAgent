"""细粒度节点验收：模板编译 + 代表性节点实跑 + 新增 SDK 能力。

前置：mock 模型在 8012（python tools/mock_llm.py --port 8012）
    python tools/granularity_test.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "app" / "runtime"))

os.environ.setdefault("MINEAGENT_BASE_URL", "http://127.0.0.1:8012/v1")
os.environ.setdefault("MINEAGENT_API_KEY", "mock-key")
os.environ.setdefault("MINEAGENT_MODEL", "mock-model")

from app.node_registry import NODE_TYPES, CATEGORIES  # noqa: E402
from app.node_templates import CODE_TEMPLATES  # noqa: E402
from app.node_templates_ext import EXT_TEMPLATES  # noqa: E402
from runtime_sdk import NodeContext  # noqa: E402

ALL = {**CODE_TEMPLATES, **EXT_TEMPLATES}
TMP = Path(tempfile.mkdtemp())
ok = True


def check(name, cond, extra=""):
    global ok
    print(f"  {'✔' if cond else '✘'} {name}{(' — ' + str(extra)) if extra else ''}")
    if not cond:
        ok = False


def load_run(kind):
    path = TMP / f"{kind}.py"
    path.write_text(ALL[kind], encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"tpl_{kind}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod.run


def run_node(kind, payload, params=None, state=None, name=None):
    ctx = NodeContext(node_id="n_test", node_name=name or kind, kind=kind,
                      params=params or {}, payload=payload, state=state if state is not None else {})
    return load_run(kind)(ctx)


print("\n[A] 节点库规模")
check("节点总数 110", len(NODE_TYPES) == 110, len(NODE_TYPES))
check("分类 13 个", len(CATEGORIES) == 13, len(CATEGORIES))
for cat in ("rag", "data", "doc", "text"):
    n = len([x for x in NODE_TYPES if x["category"] == cat])
    check(f"分类 {cat} 有节点", n > 0, f"{n} 个")

print("\n[B] 每个节点都有默认代码且可编译")
import py_compile  # noqa: E402
bad = []
for node in NODE_TYPES:
    code = node["default_code"]
    p = TMP / f"check_{node['kind']}.py"
    p.write_text(code, encoding="utf-8")
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception as exc:  # noqa: BLE001
        bad.append((node["kind"], str(exc)[:80]))
check("全部模板可编译", not bad, bad[:3] or "")

print("\n[C] 代表性节点实跑（mock 模型）")
cases = [
    ("intent_recognizer", "帮我查一下上个月的订单", {"intents": ["查询", "投诉", "闲聊"]}),
    ("query_rewrite", "那个…就是我想问下退款怎么回事", {}),
    ("text_splitter", "第一段内容。\n\n" + "第二段内容。" * 60, {"chunk_size": 160, "overlap": 20}),
    ("reranker", ["片段A：退款政策说明", "片段B：物流时效", "片段C：退款流程"], {"top_k": 2}),
    ("context_builder", [{"chunk": "退款需要 3 个工作日", "source": "faq.md"}], {"max_chars": 500}),
    ("translator", "你好世界", {"target": "English"}),
    ("deduplicator", ["a", "a", "b", "a"], {}),
    ("merger", ["x", "y"], {}),
    ("polisher", "这个东西我觉得吧大概可能是这样子的", {}),
    ("json_repair", '前面废话 {"a": 1} 后面废话', {}),
    ("cache_write", "缓存内容", {"key": "demo", "ttl": 60}),
    ("budget_guard", "继续", {"max_tokens": 999999}),
    ("table_parser", "name,age\n张三,20\n李四,30", {}),
    ("parse_text_missing", "", {}),  # 占位，下面会被过滤
]
for kind, payload, params in cases:
    if kind not in ALL:
        continue
    try:
        out = run_node(kind, payload, params)
        shown = str(out)[:60].replace("\n", " ")
        check(f"{kind} 可运行", out is not None, shown)
    except Exception as exc:  # noqa: BLE001
        check(f"{kind} 可运行", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc(limit=2)

print("\n[D] 检索链路闭环（写入 → 混合检索 → 重排 → 拼上下文）")
try:
    state = {}
    chunks = run_node("text_splitter", "退款政策：下单后 7 天内可无理由退款。\n\n"
                      "物流说明：默认顺丰，48 小时发货。", {"chunk_size": 200}, state=state)
    result = run_node("vector_indexer", chunks, {}, state=state)
    check("向量入库", result.get("indexed", 0) >= 1, result)
    state["query"] = "怎么退款"
    hits = run_node("hybrid_retriever", "怎么退款", {"top_k": 3}, state=state)
    check("混合检索有召回", bool(hits.get("vector") or hits.get("keyword")),
          f"vector={len(hits.get('vector') or [])} keyword={len(hits.get('keyword') or [])}")
    ranked = run_node("reranker", [h["text"] for h in (hits.get("vector") or [])][:3] or ["退款政策说明"],
                      {"top_k": 2}, state=state)
    check("重排返回结果", isinstance(ranked, list) and len(ranked) > 0, f"{len(ranked)} 条")
    context = run_node("context_builder", ranked, {"max_chars": 800}, state=state)
    check("上下文拼装", isinstance(context, str) and "[1]" in context, context[:60].replace("\n", " "))
except Exception as exc:  # noqa: BLE001
    check("检索链路", False, f"{type(exc).__name__}: {exc}")
    traceback.print_exc(limit=3)

print("\n[E] 新增 SDK 能力")
try:
    ctx = NodeContext("n", "t", "tool", {}, "", {})
    ctx.kv_set("k1", {"v": 1})
    check("kv 读写", ctx.kv_get("k1") == {"v": 1})
    ctx.cache_set("c1", "v1", ttl=60)
    check("缓存读写", ctx.cache_get("c1") == "v1")
    check("JSON 抽取", ctx.parse_json('说明 {"x": 2} 尾巴') == {"x": 2})
    rows = ctx.parse_table("a|b\n1|2")
    check("表格解析", rows and rows[0].get("a") == "1", rows)
    hits = ctx.retrieve("退款", top_k=2, mode="keyword")
    check("关键词检索模式", isinstance(hits, list))
except Exception as exc:  # noqa: BLE001
    check("SDK 能力", False, f"{type(exc).__name__}: {exc}")
    traceback.print_exc(limit=3)

print("\n结果：" + ("通过 ✅" if ok else "失败 ❌"))
sys.exit(0 if ok else 1)
