"""端到端冒烟测试：创建画布 → 保存落盘 → 真跑一遍 → 校验事件流。

前置：后端在 8000/8011 上运行；可选 mock 模型在 8012 上运行。

    python tools/smoke_test.py --base http://127.0.0.1:8011 --mock http://127.0.0.1:8012/v1
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path


def call(method: str, url: str, payload=None, timeout=60):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def stream_run(base: str, canvas_id: str, text: str):
    body = json.dumps({"input": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{base}/api/canvases/{canvas_id}/run", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "Accept": "text/event-stream"}, method="POST")
    events = []
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                events.append(json.loads(line[5:].strip()))
            except json.JSONDecodeError:
                pass
    return events


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    ap.add_argument("--mock", default="http://127.0.0.1:8012/v1")
    ap.add_argument("--framework", default="langchain")
    ap.add_argument("--name", default="冒烟测试画布")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    ok = True

    print("1) 配置全局模型 →", end=" ")
    call("PUT", f"{base}/api/settings", {
        "orchestrator_provider": "openai",
        "orchestrator_base_url": args.mock,
        "orchestrator_model": "mock-model",
        "orchestrator_api_key": "mock-key",
    })
    s = call("GET", f"{base}/api/settings")
    print(f"key_mask={s['orchestrator_api_key_mask']} model={s['orchestrator_model']}")

    print("2) 创建画布 →", end=" ")
    canvas = call("POST", f"{base}/api/canvases",
                  {"name": args.name, "framework": args.framework})
    cid = canvas["id"]
    print(f"slug={canvas['slug']} nodes={len(canvas['graph']['nodes'])}")
    if canvas["slug"] != args.name:
        print(f"   [warn] slug 与中文名不一致：{canvas['slug']}")

    print("3) 保存并落盘 →", end=" ")
    saved = call("POST", f"{base}/api/canvases/{cid}/save", canvas["graph"])
    print(f"files={len(saved['written_files'])} dir={Path(saved['project_dir']).name}")
    if not (Path(saved["project_dir"]) / "nodes").exists():
        print("   [FAIL] nodes 目录不存在")
        ok = False

    print("4) 运行 →", end=" ")
    events = stream_run(base, cid, "帮我写一份关于本地 Agent 编排平台的调研报告")
    kinds = [e.get("event") for e in events]
    ran = [e.get("name") for e in events if e.get("event") == "node_start"]
    end = next((e for e in events if e.get("event") == "run_end"), {})
    print(f"{len(events)} 个事件，执行节点 {len(set(ran))} 个")
    print("   节点序列：", " → ".join(ran[:14]))
    if end.get("status") != "ok":
        print("   [FAIL] 运行失败：", end.get("error") or end.get("message"))
        for e in events:
            if e.get("event") == "error":
                print("   ", str(e.get("message"))[:500])
                break
        ok = False
    else:
        print("   最终输出：", str(end.get("output"))[:120].replace("\n", " "))
    if "run_start" not in kinds:
        print("   [FAIL] 没有 run_start 事件"); ok = False

    print("5) 清理 →", end=" ")
    call("DELETE", f"{base}/api/canvases/{cid}")
    print("已删除")

    print("\n结果：" + ("通过 ✅" if ok else "失败 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
