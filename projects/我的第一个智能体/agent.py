"""我的第一个智能体 · LangChain / LangGraph 入口

本文件由 MineAgent 根据画布自动生成，可以直接修改。
优先使用框架原生实现；若本机没装对应框架，会自动回退到项目自带的 runner.py。

用法：
    python agent.py --input "你的问题"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from runtime_sdk import NodeContext  # noqa: E402

SPEC = json.loads((HERE / "agent.json").read_text(encoding="utf-8"))
NODES = {n["id"]: n for n in SPEC["nodes"]}
EDGES = SPEC["edges"]
ROUTE_SIGNALS = {"true", "false", "loop", "exit", "yes", "no", "approve", "reject"}


def load_node_module(node_id):
    import importlib.util
    node = NODES[node_id]
    path = HERE / "nodes" / node["file"]
    spec = importlib.util.spec_from_file_location("ma_" + node_id, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call_node(node_id, payload, state):
    node = NODES[node_id]
    ctx = NodeContext(node_id=node_id, node_name=node["name"], kind=node["kind"],
                      params=node.get("params") or {}, payload=payload, state=state)
    return load_node_module(node_id).run(ctx)


def run_native(user_input: str):
    from typing import Any, TypedDict
    from langgraph.graph import END, START, StateGraph

    class S(TypedDict, total=False):
        data: Any
        route: str
        state: dict

    shared = {"state": {}}

    def wrap(node_id):
        def fn(state: S) -> S:
            out = call_node(node_id, state.get("data"), shared["state"])
            if isinstance(out, str) and out.strip().lower() in ROUTE_SIGNALS:
                return {"data": state.get("data"), "route": out.strip().lower(),
                        "state": shared["state"]}
            return {"data": out, "route": "", "state": shared["state"]}
        return fn

    g = StateGraph(S)
    for nid, node in NODES.items():
        g.add_node(nid, wrap(nid))

    start = next((n["id"] for n in SPEC["nodes"] if n["kind"] == "input"), None)
    if start:
        g.add_edge(START, start)

    targets: dict = {}
    for e in EDGES:
        handle = e.get("sourceHandle")
        if handle:
            targets.setdefault(e["source"], {})[handle] = e["target"]
        else:
            g.add_edge(e["source"], e["target"])

    ends = [nid for nid in NODES if not any(e["source"] == nid for e in EDGES)]
    for nid in ends:
        if nid not in targets:
            g.add_edge(nid, END)

    for src, mapping in targets.items():
        def make_router(mapping=mapping):
            def route(state: S):
                val = (state.get("route") or "").strip().lower()
                if val in mapping:
                    return val
                return next(iter(mapping))
            return route
        g.add_conditional_edges(src, make_router(), mapping)

    app = g.compile()
    result = app.invoke({"data": user_input, "route": "", "state": {}})
    return result.get("data")


def main(user_input: str):
    try:
        out = run_native(user_input)
        print("")
        print("===== 最终结果 =====")
        print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return out
    except ImportError as exc:
        print(f"[提示] 未安装 LangGraph（{exc}），改用项目内置 runner。")
        from runner import GraphRunner
        runner = GraphRunner(SPEC)
        out = runner.run(user_input)
        print("")
        print("===== 最终结果 =====")
        print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return out


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", default="")
    args = parser.parse_args()
    text = args.input or sys.stdin.read()
    main(text)
