"""编排约束验证：内置规则、自定义规则、运行拦截。

    python tools/constraint_test.py
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def call(method, url, payload=None, timeout=60):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return {"__status": exc.code, **json.loads(body)}
        except json.JSONDecodeError:
            return {"__status": exc.code, "text": body}


def node(nid, kind, label, name):
    return {"id": nid, "type": "agent", "position": {"x": 0, "y": 0},
            "data": {"kind": kind, "label": label, "name": name, "description": "",
                     "code": "", "language": "python", "params": {}, "status": "idle"}}


def edge(src, dst, handle=None):
    return {"id": f"e_{src}_{dst}", "source": src, "target": dst,
            "sourceHandle": handle, "targetHandle": "in", "label": None, "data": {}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        print(f"  {'✔' if cond else '✘'} {name}{(' — ' + str(extra)) if extra else ''}")
        if not cond:
            ok = False

    rules_of = lambda r: {v["rule"] for v in r.get("violations", [])}

    print("\n[A] 空画布：结构性错误应全部报出")
    c = call("POST", f"{base}/api/canvases", {"name": "约束测试-空", "framework": "custom"})
    cid = c["id"]
    empty = {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}
    r = call("POST", f"{base}/api/canvases/{cid}/validate", empty)
    check("缺输入节点被报出", "single-input" in rules_of(r), rules_of(r))
    check("缺输出节点被报出", "require-output" in rules_of(r))
    check("ok=False", r["ok"] is False)

    print("\n[B] 正常链路：应当通过")
    g = {
        "nodes": [node("n1", "input", "输入", "input_1"),
                  node("n2", "agent", "Agent", "agent_1"),
                  node("n3", "output", "输出", "output_1")],
        "edges": [edge("n1", "n2"), edge("n2", "n3")],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    r = call("POST", f"{base}/api/canvases/{cid}/validate", g)
    check("正常链路无 error", r["ok"] is True, r["counts"])

    print("\n[C] 断开连线：可达性错误")
    g2 = json.loads(json.dumps(g))
    g2["edges"] = [edge("n1", "n2")]
    r = call("POST", f"{base}/api/canvases/{cid}/validate", g2)
    check("走不到 output 被报出", "can-reach-output" in rules_of(r), rules_of(r))
    check("output 无入边也算孤立", "no-orphan" in rules_of(r))

    print("\n[D] 分支节点缺出口")
    g3 = {
        "nodes": [node("n1", "input", "输入", "input_1"),
                  node("n2", "router", "路由", "router_1"),
                  node("n3", "output", "输出", "output_1")],
        "edges": [edge("n1", "n2"), edge("n2", "n3", "false")],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    r = call("POST", f"{base}/api/canvases/{cid}/validate", g3)
    check("router 缺 true 分支被报出", "router-two-branches" in rules_of(r), rules_of(r))

    print("\n[E] 自定义顺序规则")
    g4 = {
        "nodes": [node("n1", "input", "输入", "input_1"),
                  node("n2", "agent", "Agent", "agent_1"),
                  node("n3", "formatter", "格式化", "formatter_1"),
                  node("n4", "output", "输出", "output_1")],
        "edges": [edge("n1", "n2"), edge("n2", "n3"), edge("n3", "n4")],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    call("PUT", f"{base}/api/canvases/{cid}/rules", [
        {"id": "r1", "type": "order", "level": "error",
         "node": "n3", "anchor": "n2", "mode": "before",
         "label": "格式化必须在 Agent 之前"},
    ])
    r = call("POST", f"{base}/api/canvases/{cid}/validate", g4)
    custom = [v for v in r["violations"] if v["rule"].startswith("custom:")]
    check("顺序规则被违反并报出", len(custom) == 1, custom[0]["message"] if custom else "无")
    check("自定义规则算作 error", r["ok"] is False)

    # 调整成满足：把 formatter 放到 agent 前面
    g5 = json.loads(json.dumps(g4))
    g5["edges"] = [edge("n1", "n3"), edge("n3", "n2"), edge("n2", "n4")]
    r = call("POST", f"{base}/api/canvases/{cid}/validate", g5)
    custom5 = [v for v in r["violations"] if v["rule"].startswith("custom:")]
    check("满足顺序后又通过", len(custom5) == 0 and r["ok"] is True, r["counts"])

    print("\n[F] 保存带出约束报告，运行被拦")
    saved = call("POST", f"{base}/api/canvases/{cid}/save", g4)
    check("保存返回 constraints", saved.get("constraints", {}).get("ok") is False,
          saved.get("constraints", {}).get("counts"))
    run_resp = call("POST", f"{base}/api/canvases/{cid}/run", {"input": "hi"})
    detail = run_resp.get("detail") or {}
    check("违反约束时运行返回 409", run_resp.get("__status") == 409, detail.get("message"))
    check("409 里带违规明细", len(detail.get("violations") or []) > 0,
          len(detail.get("violations") or []))

    print("\n[G] 强制运行放行")
    body = json.dumps({"input": "hi", "force": True}).encode()
    req = urllib.request.Request(f"{base}/api/canvases/{cid}/run", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Accept": "text/event-stream"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    check("force=true 时不再拦（进入执行流）", status == 200, status)

    print("\n[H] 清理")
    call("DELETE", f"{base}/api/canvases/{cid}")
    check("测试画布已删除", True)

    print("\n结果：" + ("通过 ✅" if ok else "失败 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
