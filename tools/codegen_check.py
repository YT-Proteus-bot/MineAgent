"""生成器回归检查：把画布编译成 agent.py，静态校验图的完整性。

用法：
    python tools/codegen_check.py                # 用 projects/*/canvas.snapshot.json
    python tools/codegen_check.py --api          # 拉当前后端里所有画布（含蓝图）
    python tools/codegen_check.py --api --verbose

退出码非 0 表示有画布生成的图跑不通，可直接当 CI 门禁用。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.codegen.generators import build_spec  # noqa: E402
from app.codegen.graphcheck import check_code  # noqa: E402
from app.codegen.native import (  # noqa: E402
    AGENT_KINDS,
    TOOL_KINDS,
    _kind_of,
    render_agent_full,
)

LANGGRAPH_FRAMEWORKS = {
    "langchain", "langgraph", "custom", "dify", "metagpt",
    "openai_agents", "smolagents", "agno", "semantic_kernel",
}


def check_canvas(name: str, slug: str, framework: str, graph: dict, verbose: bool) -> list[str]:
    spec = build_spec(name, slug, framework, graph)
    try:
        code, blocks = render_agent_full(spec, framework)
    except Exception as exc:  # noqa: BLE001
        return [f"渲染失败：{type(exc).__name__}: {exc}"]
    try:
        compile(code, f"<{slug}>", "exec")
    except SyntaxError as exc:
        return [f"生成的 agent.py 语法错误：第 {exc.lineno} 行 {exc.msg}"]

    if framework not in LANGGRAPH_FRAMEWORKS or not spec.get("edges"):
        return []

    issues = check_code(spec, code, blocks, TOOL_KINDS, AGENT_KINDS, _kind_of)
    if verbose and not issues:
        graph_nodes = [n for n in spec["nodes"] if _kind_of(n) not in TOOL_KINDS]
        tools = [n for n in spec["nodes"] if _kind_of(n) in TOOL_KINDS]
        agents = [n for n in graph_nodes if _kind_of(n) in AGENT_KINDS]
        print(f"    nodes={len(graph_nodes)} tools={len(tools)} agents={len(agents)}")
    return issues


def load_from_projects() -> list[tuple[str, str, str, dict]]:
    cases = []
    for snap in sorted((ROOT / "projects").glob("*/canvas.snapshot.json")):
        graph = json.loads(snap.read_text(encoding="utf-8"))
        slug = snap.parent.name
        cases.append((graph.get("name") or slug, slug, graph.get("framework") or "langchain", graph))
    return cases


def load_from_api() -> list[tuple[str, str, str, dict]]:
    import urllib.request

    base = "http://127.0.0.1:8000"
    with urllib.request.urlopen(base + "/api/canvases", timeout=30) as r:
        canvases = json.loads(r.read().decode("utf-8"))
    cases = []
    for c in canvases:
        with urllib.request.urlopen(f"{base}/api/canvases/{c['id']}", timeout=60) as r:
            detail = json.loads(r.read().decode("utf-8"))
        graph = detail.get("graph") or {}
        if not graph.get("nodes"):
            continue
        slug = detail.get("slug") or c["id"]
        cases.append((c["name"], slug, graph.get("framework") or "langchain", graph))
    return cases


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", action="store_true", help="从运行中的后端拉全部画布")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    cases = load_from_api() if args.api else load_from_projects()
    if not cases:
        print("没有找到可检查的画布")
        return 1

    failed = 0
    for name, slug, framework, graph in cases:
        issues = check_canvas(name, slug, framework, graph, args.verbose)
        print(f"[{'OK  ' if not issues else 'FAIL'}] {name}  ({framework})")
        for item in issues:
            print(f"       - {item}")
        failed += bool(issues)

    print("-" * 70)
    print(f"{len(cases) - failed}/{len(cases)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
