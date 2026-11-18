"""给 SmolAgents 画布补上循环控制：observation 之后先过 router，再由它决定继续还是收尾。"""
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8000"
GAP = 380


def call(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def node(nid, kind, label, x, params=None, role="main"):
    return {"id": nid, "type": "agent", "position": {"x": x, "y": 0},
            "data": {"kind": kind, "label": label, "name": f"{kind}_{nid[1:]}",
                     "description": "", "code": "", "language": "python",
                     "params": params or {}, "org": {}, "role": role}}


def edge(eid, s, t, handle="out", label=None):
    return {"id": eid, "source": s, "target": t, "sourceHandle": handle,
            "targetHandle": "in", "type": "agent",
            "label": label, "data": {"branch": label}}


def main():
    canvases = call("GET", "/api/canvases")
    c = next(x for x in canvases if x["name"] == "开源 · SmolAgents 代码行动")

    nodes = [
        node("n1", "input", "任务", 0, role="input"),
        node("n2", "agent", "CodeAgent", GAP,
             {"mode": "react", "max_steps": 4,
              "system_prompt": "用 Python 代码表达每一步行动，能算就直接算。"}),
        node("n3", "code_interpreter", "代码执行沙箱", GAP * 2),
        node("n4", "observation", "观察执行结果", GAP * 3, role="aux"),
        node("n5", "router", "还要继续写代码吗？", GAP * 4,
             {"question": "执行结果是否已经足以回答原问题？若足够请回答 true。",
              "max_loops": 3, "exit_handle": "true"}),
        node("n6", "output", "输出", GAP * 5, role="output"),
    ]
    edges = [
        edge("e1", "n1", "n2"),
        edge("e2", "n2", "n3"),
        edge("e3", "n3", "n4"),
        edge("e4", "n4", "n5"),
        edge("e5", "n5", "n6", "true", "完成"),
        edge("e6", "n5", "n2", "false", "继续"),
    ]
    graph = {"nodes": nodes, "edges": edges,
             "viewport": {"x": 0, "y": 0, "zoom": 0.62}, "background": {}}
    detail = call("GET", f"/api/canvases/{c['id']}")
    graph["background"] = detail["background"]
    res = call("POST", f"/api/canvases/{c['id']}/save", graph)
    print(f"✔ SmolAgents 画布已重排为 {len(nodes)} 节点 / {len(edges)} 边")
    print("  结构: input → CodeAgent → 沙箱 → 观察 → router →（完成/继续）")
    counts = res.get("constraints", {}).get("counts")
    print("  约束:", counts)


if __name__ == "__main__":
    main()
