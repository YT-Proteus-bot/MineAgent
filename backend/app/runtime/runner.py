"""画布项目执行器。

用法：
    python runner.py --input "用户输入"
    python runner.py --input "用户输入" --json

它读取同目录的 agent.json（画布图定义），逐个加载 nodes/*.py 执行，
过程以 `@@EVENT@@{json}` 行输出到 stdout，节点里的 print 被重定向到 stderr。

执行语义：
- 从 input 节点开始，沿边推进；
- 多入边节点会先把它所有「还没执行过」的上游分支补齐，再合并输入（fan-in）；
- 只有一个输出端口、但返回值是 "true"/"false"/"loop"/"exit" 等多端口信号的节点，
  被当作「路由节点」：走对应出边，且把输入原样透传给下游（不改数据）；
- 走回边（目标已执行过）时按循环处理，受 max_visits 限制。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import runtime_sdk  # noqa: E402
from runtime_sdk import EVENT_PREFIX, NodeContext, ToolSpec, emit_event  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent
AGENT_FILE = PROJECT_DIR / "agent.json"
NODES_DIR = PROJECT_DIR / "nodes"

TOOL_KINDS = {
    "tool", "function", "mcp_tool", "crewai_tool", "http_request", "web_search",
    "code_interpreter", "sql_query", "rag_retriever", "file_io", "browser", "shell",
}
AGENT_KINDS = {"agent", "autogen_tool_agent", "group_chat", "supervisor", "worker"}
ROUTE_SIGNALS = {"true", "false", "loop", "exit", "yes", "no", "approve", "reject"}


def log_stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


class GraphRunner:
    def __init__(self, spec: Dict[str, Any], run_id: str = ""):
        self.spec = spec
        self.run_id = run_id or f"run-{int(time.time())}"
        self.nodes: Dict[str, Dict[str, Any]] = {n["id"]: n for n in spec.get("nodes", [])}
        self.edges: List[Dict[str, Any]] = spec.get("edges", [])
        self.out_edges: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.in_edges: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for e in self.edges:
            self.out_edges[e["source"]].append(e)
            self.in_edges[e["target"]].append(e)
        self.state: Dict[str, Any] = {}
        self.outputs: Dict[str, Any] = {}
        self.visits: Dict[str, int] = defaultdict(int)
        self.max_visits = int(spec.get("max_visits", 8))
        self.module_cache: Dict[str, Any] = {}
        self.final_output: Any = None

    # ---------------- 模块加载 ----------------
    def load_module(self, node: Dict[str, Any]):
        path = NODES_DIR / node.get("file", f"{node['name']}.py")
        key = str(path)
        if key in self.module_cache:
            return self.module_cache[key]
        if not path.exists():
            raise FileNotFoundError(f"节点文件不存在：{path.name}")
        name = f"ma_node_{node['id']}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 {path.name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        if not hasattr(module, "run"):
            raise AttributeError(f"{path.name} 缺少 run(ctx) 函数")
        self.module_cache[key] = module
        return module

    # ---------------- 工具注入 ----------------
    def tools_for(self, node_id: str) -> List[ToolSpec]:
        found: List[str] = []
        seen = {node_id}
        queue = [node_id]
        while queue:
            cur = queue.pop(0)
            for e in self.out_edges.get(cur, []):
                tid = e["target"]
                if tid in seen:
                    continue
                seen.add(tid)
                target = self.nodes.get(tid)
                if not target:
                    continue
                if target["kind"] in TOOL_KINDS:
                    found.append(tid)
                    queue.append(tid)
                elif target["kind"] in AGENT_KINDS:
                    continue  # 不跨 agent 借用工具
        specs: List[ToolSpec] = []
        for tid in found:
            tnode = self.nodes[tid]
            specs.append(ToolSpec(
                name=tnode.get("name") or tid,
                description=tnode.get("label") or tnode["kind"],
                func=(lambda _tid: lambda **kw: self.execute_node(_tid, kw, nested=True))(tid),
            ))
        return specs

    # ---------------- 单节点执行 ----------------
    def execute_node(self, node_id: str, payload: Any, nested: bool = False) -> Any:
        node = self.nodes[node_id]
        started = time.time()
        self.visits[node_id] += 1
        if not nested:
            emit_event({"event": "node_start", "node": node_id, "name": node.get("name"),
                        "kind": node.get("kind"), "label": node.get("label"),
                        "visit": self.visits[node_id]})
        ctx = NodeContext(node_id=node_id, node_name=node.get("name") or node_id,
                          kind=node.get("kind", "llm"), params=node.get("params") or {},
                          payload=payload, state=self.state, run_id=self.run_id)
        ctx.tools = self.tools_for(node_id)
        if self.visits[node_id] > self.max_visits:
            raise RuntimeError(f"节点 {node.get('name')} 执行次数超过上限 {self.max_visits}，疑似死循环")
        try:
            module = self.load_module(node)
            try:
                result = module.run(ctx, **payload) if isinstance(payload, dict) and _accepts_kwargs(module.run) else module.run(ctx)
            except TypeError as exc:
                if "unexpected keyword" in str(exc):
                    result = module.run(ctx)
                else:
                    raise
        except Exception as exc:  # noqa: BLE001
            emit_event({"event": "error", "node": node_id, "name": node.get("name"),
                        "message": str(exc), "traceback": traceback.format_exc()[-3000:]})
            self.state["last_error"] = str(exc)
            raise
        self.outputs[node_id] = result
        if not nested:
            emit_event({"event": "node_end", "node": node_id, "name": node.get("name"),
                        "kind": node.get("kind"),
                        "duration_ms": int((time.time() - started) * 1000),
                        "output": _short(result)})
        return result

    # ---------------- 前驱补齐 ----------------
    def ensure_upstream(self, node_id: str, stack: set) -> None:
        if node_id in self.outputs or node_id in stack:
            return
        stack.add(node_id)
        for e in self.in_edges.get(node_id, []):
            src = e["source"]
            if src not in self.outputs:
                self.ensure_upstream(src, stack)
                if src in self.outputs or src in self.nodes:
                    if src not in self.outputs:
                        continue
                    branch = self._branch_of(src)
                    self.advance_from(src, branch, record=False)
        stack.discard(node_id)

    def _branch_of(self, node_id: str) -> Optional[str]:
        val = self.state.pop("__branch__", None)
        return val

    def merged_input(self, node_id: str) -> Any:
        ins = [e["source"] for e in self.in_edges.get(node_id, []) if e["source"] in self.outputs]
        if not ins:
            return self.state.get("__last_payload__")
        if len(ins) == 1:
            return self.outputs[ins[0]]
        merged = {}
        for src in ins:
            merged[self.nodes[src].get("name") or src] = self.outputs[src]
        return merged

    # ---------------- 路由选择 ----------------
    def pick_next(self, node_id: str, result: Any) -> Optional[Dict[str, Any]]:
        outs = self.out_edges.get(node_id, [])
        if not outs:
            return None
        node = self.nodes[node_id]
        handles = node.get("outputs") or ["out"]
        branch = self.state.pop("__branch__", None)
        if branch is None and len(handles) > 1 and isinstance(result, str) \
                and result.strip().lower() in ROUTE_SIGNALS:
            branch = result.strip().lower()
        if branch is not None:
            for e in outs:
                if (e.get("sourceHandle") or "").lower() == str(branch).lower():
                    return {"edge": e, "branch": branch}
            # 分支名对不上时，按位置兜底
            idx = {"true": 0, "yes": 0, "approve": 0, "loop": 0}.get(str(branch).lower(), 1)
            if idx < len(handles):
                for e in outs:
                    if (e.get("sourceHandle") or "") == handles[idx]:
                        return {"edge": e, "branch": branch}
        # 单端口：取第一条边
        for e in outs:
            if not e.get("sourceHandle") or e.get("sourceHandle") == handles[0]:
                return {"edge": e, "branch": None}
        return {"edge": outs[0], "branch": None}

    def advance_from(self, node_id: str, branch: Optional[str], record: bool = True) -> Optional[str]:
        result = self.outputs.get(node_id)
        nxt = self.pick_next(node_id, result)
        if nxt is None:
            return None
        target = nxt["edge"]["target"]
        return target

    # ---------------- 主流程 ----------------
    def run(self, user_input: str) -> Any:
        start = next((n for n in self.spec.get("nodes", []) if n.get("kind") == "input"), None)
        if start is None:
            raise RuntimeError("画布缺少 input 节点，无法运行")
        emit_event({"event": "run_start", "run_id": self.run_id,
                    "project": self.spec.get("name"), "framework": self.spec.get("framework"),
                    "nodes": len(self.nodes), "edges": len(self.edges)})

        cur = start["id"]
        payload = user_input
        guard = 0
        max_steps = 400
        while cur is not None and guard < max_steps:
            guard += 1
            node = self.nodes.get(cur)
            if node is None:
                break
            # 补齐未执行的上游分支
            for e in self.in_edges.get(cur, []):
                if e["source"] not in self.outputs:
                    self.ensure_upstream(e["source"], {cur})

            if len(self.in_edges.get(cur, [])) > 1 and not (node.get("kind") == "input"):
                payload = self.merged_input(cur)

            self.state["__last_payload__"] = payload
            result = self.execute_node(cur, payload)

            handles = node.get("outputs") or ["out"]
            is_router = len(handles) > 1 and isinstance(result, str) \
                and result.strip().lower() in ROUTE_SIGNALS
            next_payload = payload if is_router else result

            nxt = self.pick_next(cur, result)
            if nxt is None:
                self.final_output = result
                if node.get("kind") == "output":
                    emit_event({"event": "final", "output": result})
                break
            target = nxt["edge"]["target"]
            if nxt.get("branch"):
                emit_event({"event": "route", "node": cur, "branch": nxt["branch"],
                            "target": target})
            if self.visits[target] >= self.max_visits:
                emit_event({"event": "log", "level": "warn",
                            "message": f"节点 {self.nodes[target].get('name')} 达到最大访问次数，停止"})
                self.final_output = result
                break
            cur = target
            payload = next_payload

        if self.final_output is None:
            self.final_output = next(iter(reversed(list(self.outputs.values()))), "")
        return self.final_output


def _accepts_kwargs(func) -> bool:
    import inspect
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    return any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()) or len(sig.parameters) > 1


def _short(value: Any, limit: int = 1500) -> Any:
    if isinstance(value, str):
        return value[:limit]
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return str(value)[:limit]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="")
    parser.add_argument("--json", action="store_true", help="只输出最终结果 JSON")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()

    if not AGENT_FILE.exists():
        emit_event({"event": "error", "message": f"缺少 {AGENT_FILE.name}，请先在网页上保存画布"})
        return 2
    spec = json.loads(AGENT_FILE.read_text(encoding="utf-8"))

    real_stdout = sys.stdout
    runtime_sdk.EVENT_STREAM = real_stdout
    runner = GraphRunner(spec, run_id=args.run_id)
    status = "ok"
    try:
        sys.stdout = sys.stderr  # 节点里的 print 只能进 stderr
        output = runner.run(args.input)
    except Exception as exc:  # noqa: BLE001
        sys.stdout = real_stdout
        emit_event({"event": "run_end", "status": "error", "message": str(exc),
                    "output": _short(runner.final_output or "")})
        return 1
    finally:
        sys.stdout = real_stdout

    emit_event({"event": "run_end", "status": status,
                "output": output if isinstance(output, str) else _short(output),
                "state": _short({k: v for k, v in runner.state.items() if not k.startswith("__")})})
    if args.json:
        real_stdout.write(json.dumps({"output": output}, ensure_ascii=False, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
