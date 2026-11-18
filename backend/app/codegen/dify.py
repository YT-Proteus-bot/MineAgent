"""Dify Workflow DSL 导出。

Dify 是可视化平台，不是 Python 框架。所谓「可运行」= 生成一份能直接导入
Dify 的 workflow DSL，再用它的 API 触发。这里负责把画布编译成 DSL。

DSL 版本按 Dify 1.x 的 `kind: app` + `workflow.graph` 结构生成；
不同 Dify 版本对个别字段可能有差异，导入后在编辑器里另存一次即可对齐。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


# 画布节点类型 → Dify 节点类型
_KIND_MAP = {
    "input": "start",
    "output": "end",
    "llm": "llm",
    "agent": "agent",
    "planner": "llm",
    "observation": "llm",
    "formatter": "llm",
    "summarize": "llm",
    "classify": "llm",
    "extract": "llm",
    "translate": "llm",
    "rewrite": "llm",
    "router": "if-else",
    "condition": "if-else",
    "branch": "if-else",
    "switch": "if-else",
    "rag_retriever": "knowledge-retrieval",
    "rag": "knowledge-retrieval",
    "retriever": "knowledge-retrieval",
    "code_interpreter": "code",
    "tool": "tool",
    "http_request": "http-request",
    "http": "http-request",
    "file_io": "code",
    "sql_query": "code",
    "template": "template-transform",
    "prompt": "llm",
    "memory": "variable-assigner",
    "delay": "code",
}


def _yaml(value: Any, indent: int = 0) -> str:
    """最小 YAML 序列化：dict / list / str / 基础标量。"""
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                lines.append(_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = []
        for item in value:
            if isinstance(item, dict):
                body = _yaml(item, indent + 2)
                first, *rest = body.split("\n")
                lines.append(f"{pad}- {first.strip()}")
                lines.extend(rest)
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.append(_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}- {_scalar(item)}")
        return "\n".join(lines)
    return f"{pad}{_scalar(value)}"


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list) and not value:
        return "[]"
    if isinstance(value, dict) and not value:
        return "{}"
    text = str(value)
    if text == "":
        return "''"
    if any(ch in text for ch in ":#{}[]&*!|>'\"%@`\n") or text.strip() != text:
        return json.dumps(text, ensure_ascii=False)
    return text


def _node_type(kind: str) -> str:
    return _KIND_MAP.get(kind, "llm")


def _node_data(node: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
    kind = node.get("kind") or "llm"
    dtype = _node_type(kind)
    title = node.get("label") or node.get("name") or dtype
    params = node.get("params") or {}
    base: Dict[str, Any] = {"title": title, "type": dtype, "desc": ""}

    if dtype == "start":
        base["variables"] = [{"label": "用户输入", "max_length": 2000,
                              "options": [], "required": True,
                              "type": "paragraph", "variable": "input"}]
    elif dtype == "end":
        base["outputs"] = [{"value_selector": [], "variable": "output"}]
    elif dtype == "llm":
        system = params.get("system_prompt") or node.get("description") or ""
        base.update({
            "model": {
                "provider": model.get("provider") or "openai",
                "name": model.get("model") or "gpt-4o-mini",
                "mode": "chat",
                "completion_params": {"temperature": float(params.get("temperature", 0.3))},
            },
            "prompt_template": [
                {"role": "system", "text": str(system)},
                {"role": "user", "text": "{{#context#}}"},
            ],
            "context": {"enabled": False, "variable_selector": []},
            "vision": {"enabled": False},
            "variables": [],
        })
    elif dtype == "if-else":
        base["cases"] = [{"case_id": "true", "logical_operator": "and",
                          "conditions": [{"comparison_operator": "not empty",
                                          "value": "", "variable_selector": []}]}]
    elif dtype == "knowledge-retrieval":
        base["query_variable_selector"] = []
        base["dataset_ids"] = []
        base["retrieval_mode"] = "multiple"
    elif dtype == "tool":
        base["provider_id"] = params.get("server") or ""
        base["tool_name"] = params.get("tool") or ""
        base["tool_parameters"] = {}
        base["tool_configurations"] = {}
    elif dtype == "http-request":
        base["method"] = "get"
        base["url"] = params.get("url") or ""
        base["authorization"] = {"type": "no-auth"}
        base["headers"] = ""
        base["params"] = ""
        base["body"] = {"type": "none", "data": []}
    elif dtype == "code":
        base["code_language"] = "python3"
        base["code"] = "# 由画布节点代码迁移；导入后可直接编辑\nreturn {}"
        base["variables"] = []
        base["outputs"] = {"result": {"children": None, "type": "string"}}
    elif dtype == "template-transform":
        base["template"] = node.get("description") or ""
        base["variables"] = []
    elif dtype == "variable-assigner":
        base["items"] = []
    elif dtype == "agent":
        base.update({
            "agent_strategy_provider_name": "langgenius/agent",
            "agent_strategy_name": "function_calling",
            "agent_strategy_label": "FunctionCalling",
            "agent_parameters": {},
            "output_schema": None,
        })
    return base


def render_workflow_dsl(spec: Dict[str, Any], model: Dict[str, Any]) -> str:
    """把画布编译成 Dify workflow DSL（YAML 文本）。"""
    nodes: List[Dict[str, Any]] = []
    positions: Dict[str, Dict[str, int]] = {}

    ordered = [n for n in spec.get("nodes", [])]
    for idx, node in enumerate(ordered):
        positions[node["id"]] = {"x": 80 + (idx % 6) * 280, "y": 80 + (idx // 6) * 220}
        nodes.append({
            "id": node["id"],
            "type": "custom",
            "position": positions[node["id"]],
            "positionAbsolute": positions[node["id"]],
            "width": 244,
            "height": 100,
            "selected": False,
            "sourcePosition": "right",
            "targetPosition": "left",
            "data": _node_data(node, model),
        })

    edges: List[Dict[str, Any]] = []
    kinds = {n["id"]: _node_type(n.get("kind") or "llm") for n in ordered}
    for idx, edge in enumerate(spec.get("edges", [])):
        src, tgt = edge["source"], edge["target"]
        handle = str(edge.get("sourceHandle") or "")
        edge_data: Dict[str, Any] = {
            "sourceType": kinds.get(src, "llm"),
            "targetType": kinds.get(tgt, "llm"),
            "isInIteration": False,
        }
        if handle:
            edge_data["sourceHandle"] = handle
        edges.append({
            "id": f"e{idx}-{src}-{tgt}",
            "source": src,
            "sourceHandle": handle or "source",
            "target": tgt,
            "targetHandle": "target",
            "type": "custom",
            "data": edge_data,
        })

    dsl = {
        "app": {
            "name": spec.get("name") or "MineAgent Workflow",
            "description": "由 MineAgent 画布导出的 Dify Workflow",
            "mode": "workflow",
            "icon": "🤖",
            "icon_background": "#FFEAD5",
            "use_icon_as_answer_icon": False,
        },
        "dependencies": [],
        "kind": "app",
        "version": "0.1.5",
        "workflow": {
            "conversation_variables": [],
            "environment_variables": [],
            "features": {
                "file_upload": {
                    "allowed_file_extensions": [], "allowed_file_types": [],
                    "allowed_file_upload_methods": [], "enabled": False,
                    "number_limits": 3,
                },
                "retriever_resource": {"enabled": True},
                "sensitive_word_avoidance": {"enabled": False},
                "speech_to_text": {"enabled": False},
                "suggested_questions": [],
                "suggested_questions_after_answer": {"enabled": False},
                "text_to_speech": {"enabled": False, "language": "", "voice": ""},
            },
            "graph": {
                "edges": edges,
                "nodes": nodes,
                "viewport": {"x": 0, "y": 0, "zoom": 0.8},
            },
        },
    }
    return _yaml(dsl) + "\n"


DIFY_CLIENT = '''"""用 Dify API 触发这个工作流。

用法：
    set DIFY_BASE_URL=https://你的-dify 域名/v1
    set DIFY_API_KEY=app-xxxxxxxx
    python dify_client.py "你的问题"

也可以把 dify_workflow.yml 直接导入 Dify：
    Dify 控制台 → 工作室 → 导入 DSL 文件
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request


def run_workflow(query: str) -> dict:
    base = (os.environ.get("DIFY_BASE_URL") or "http://127.0.0.1/v1").rstrip("/")
    key = os.environ.get("DIFY_API_KEY") or ""
    if not key:
        raise SystemExit("请先设置环境变量 DIFY_API_KEY（Dify 应用的 API 密钥）")
    payload = {
        "inputs": {"input": query},
        "response_mode": "blocking",
        "user": "mineagent",
    }
    req = urllib.request.Request(
        f"{base}/workflows/run",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def main() -> None:
    query = " ".join(sys.argv[1:]) or "你好"
    data = run_workflow(query)
    outputs = ((data.get("data") or {}).get("outputs") or {})
    print(json.dumps(outputs or data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
'''
