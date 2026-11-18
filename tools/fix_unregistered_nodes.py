"""把 Super-agent 画布里未注册的 merge 节点换成节点库里已有的 merger。"""
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    meta = call("GET", "/api/meta")
    library = {n["kind"]: n for n in meta["nodes"]}

    canvases = [c for c in call("GET", "/api/canvases")
                if c["name"].startswith(("开源 ·", "闭源 ·"))]
    fixed = 0
    for c in canvases:
        detail = call("GET", f"/api/canvases/{c['id']}")
        nodes = detail["graph"]["nodes"]
        changed = False
        for n in nodes:
            kind = n["data"]["kind"]
            if kind not in library:
                # 用名字最接近的已注册节点替换
                alias = {"merge": "merger"}.get(kind)
                if alias and alias in library:
                    n["data"]["kind"] = alias
                    if n["data"]["name"].startswith(kind + "_"):
                        n["data"]["name"] = alias + n["data"]["name"][len(kind):]
                    changed = True
                    print(f"  {c['name']}: {kind} → {alias}")
                    fixed += 1
        if changed:
            call("POST", f"/api/canvases/{c['id']}/save", {
                "nodes": nodes, "edges": detail["graph"]["edges"],
                "viewport": detail["graph"]["viewport"],
                "background": detail["background"],
            })

    # 复核
    left = []
    for c in canvases:
        detail = call("GET", f"/api/canvases/{c['id']}")
        for n in detail["graph"]["nodes"]:
            if n["data"]["kind"] not in library:
                left.append((c["name"], n["data"]["kind"]))
    print(f"\n修复 {fixed} 处；仍未注册的节点: {left or '无'}")


if __name__ == "__main__":
    main()
