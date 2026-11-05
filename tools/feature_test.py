"""新功能验证：agent 推理模式、多 agent 组织关系（delegate）、节点级模型。

前置：后端在 8000，mock 模型在 8012。
    python tools/mock_llm.py --port 8012
    python tools/feature_test.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def call(method, url, payload=None, timeout=60):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def stream_run(base, canvas_id, text):
    body = json.dumps({"input": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/canvases/{canvas_id}/run", data=body,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Accept": "text/event-stream"}, method="POST")
    events = []
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass
    return events


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--mock", default="http://127.0.0.1:8012/v1")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        print(f"  {'✔' if cond else '✘'} {name}{(' — ' + str(extra)) if extra else ''}")
        if not cond:
            ok = False

    print("\n[A] 节点级模型覆盖（SDK 层）")
    sys.path.insert(0, str(ROOT / "backend" / "app" / "runtime"))
    os.environ["MINEAGENT_KEY_TESTNODE"] = "sk-node-level-key"
    from runtime_sdk import NodeContext  # noqa: E402

    ctx = NodeContext("n3", "agent_3", "agent", {}, "", {},
                      model_override={"model": "deepseek-chat", "base_url": "https://node.example/v1",
                                      "api_key_env": "MINEAGENT_KEY_TESTNODE"})
    check("模型名被节点配置覆盖", ctx.cfg["model"] == "deepseek-chat", ctx.cfg["model"])
    check("base_url 被节点配置覆盖", ctx.cfg["base_url"] == "https://node.example/v1")
    check("api key 从环境变量取到", ctx.cfg["api_key"] == "sk-node-level-key")

    plain = NodeContext("n4", "plain", "agent", {}, "", {})
    check("没配节点模型时用项目配置", plain.cfg["model"] != "deepseek-chat", plain.cfg["model"])

    print("\n[B] 准备后端与 mock")
    call("PUT", f"{base}/api/settings", {
        "orchestrator_provider": "openai",
        "orchestrator_base_url": args.mock,
        "orchestrator_model": "mock-model",
        "orchestrator_api_key": "mock-key",
    })
    check("全局模型已指向 mock", True)

    print("\n[C] Agent 推理模式（单 agent，plan_execute）")
    canvas = call("POST", f"{base}/api/canvases",
                  {"name": "模式验证画布", "framework": "custom"})
    cid = canvas["id"]
    graph = canvas["graph"]
    agent_node = next((n for n in graph["nodes"] if n["data"]["kind"] == "llm"), None)
    if agent_node is None:
        agent_node = graph["nodes"][1]
    agent_node["data"]["kind"] = "agent"
    agent_node["data"]["params"] = {"mode": "plan_execute", "max_steps": 4}
    agent_node["data"]["name"] = "agent_mode_test"
    agent_node["data"]["code"] = (
        "from runtime_sdk import NodeContext\n\n\n"
        "def run(ctx: NodeContext):\n"
        "    return ctx.agent(task=ctx.text, tools=ctx.tools,\n"
        "                     mode=ctx.params.get('mode', 'react'), max_steps=ctx.params.get('max_steps', 4))\n"
    )
    saved = call("POST", f"{base}/api/canvases/{cid}/save", graph)
    spec = json.loads((Path(saved["project_dir"]) / "agent.json").read_text(encoding="utf-8"))
    spec_node = next((n for n in spec["nodes"] if n["name"] == "agent_mode_test"), None)
    check("mode 落进 agent.json", bool(spec_node) and spec_node["params"].get("mode") == "plan_execute",
          spec_node["params"].get("mode") if spec_node else "missing")

    events = stream_run(base, cid, "给一个三步计划：调研、分析、成稿")
    modes = [e.get("mode") for e in events if e.get("event") == "agent_mode"]
    plan_steps = [e for e in events if e.get("event") == "agent_step" and e.get("mode") == "plan_execute"]
    end = next((e for e in events if e.get("event") == "run_end"), {})
    check("运行时进入 plan_execute 模式", modes and modes[0] == "plan_execute", modes)
    check("产生规划步骤事件", len(plan_steps) >= 1, f"{len(plan_steps)} 个")
    check("运行成功", end.get("status") == "ok", str(end.get("error") or "")[:120])

    print("\n[D] 多 agent 组织关系（supervisor → 2 个 worker 委派）")
    canvas2 = call("POST", f"{base}/api/canvases",
                   {"name": "组织关系验证", "framework": "metagpt"})
    cid2 = canvas2["id"]
    g2 = canvas2["graph"]
    sup = next((n for n in g2["nodes"] if n["data"]["kind"] == "supervisor"), None)
    workers = [n for n in g2["nodes"] if n["data"]["kind"] == "worker"]
    check("模板里有 supervisor 与 worker", bool(sup) and len(workers) >= 2,
          f"supervisor={bool(sup)} workers={len(workers)}")
    if sup and len(workers) >= 2:
        sup["data"]["org"] = {"superior": "", "subordinates": [w["id"] for w in workers],
                              "peers": []}
        for w in workers:
            w["data"]["org"] = {"superior": sup["id"], "subordinates": [], "peers": []}
            w["data"]["params"]["mode"] = "simple"
        sup["data"]["code"] = (
            "from runtime_sdk import NodeContext\n\n\n"
            "def run(ctx: NodeContext):\n"
            "    names = ctx.subordinates\n"
            "    if not names:\n"
            "        return ctx.llm(ctx.text)\n"
            "    results = {}\n"
            "    for name in names:\n"
            "        results[name] = ctx.delegate(name, '子任务：' + ctx.text)\n"
            "    summary = '\\n\\n'.join(f'### {k}\\n{v}' for k, v in results.items())\n"
            "    return ctx.llm(f'汇总这些结果：\\n{summary}')\n"
        )
        saved2 = call("POST", f"{base}/api/canvases/{cid2}/save", g2)
        spec2 = json.loads((Path(saved2["project_dir"]) / "agent.json").read_text(encoding="utf-8"))
        sup_spec = next((n for n in spec2["nodes"] if n["id"] == sup["id"]), {})
        check("组织关系落进 agent.json", len(sup_spec.get("org", {}).get("subordinates", [])) == 2,
              sup_spec.get("org"))

        events2 = stream_run(base, cid2, "帮我分析一下国产 Agent 框架的差异")
        delegates = [e for e in events2 if e.get("event") == "delegate"]
        done = [e for e in events2 if e.get("event") == "delegate_done"]
        end2 = next((e for e in events2 if e.get("event") == "run_end"), {})
        check("主管向下级派发任务", len(delegates) >= 2, f"{len(delegates)} 次")
        check("下级返回结果", len(done) >= 2, f"{len(done)} 次")
        check("组织流程运行成功", end2.get("status") == "ok", str(end2.get("error") or "")[:120])

    print("\n[E] 清理")
    call("DELETE", f"{base}/api/canvases/{cid}")
    call("DELETE", f"{base}/api/canvases/{cid2}")
    check("测试画布已删除", True)

    print("\n结果：" + ("通过 ✅" if ok else "失败 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
