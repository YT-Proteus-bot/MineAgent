"""后端边缘场景验证：框架切换、改名（目录同步）、删除清理、文件浏览。

    python tools/api_test.py --base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"


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

    print("\n[A] 框架切换")
    c = call("POST", f"{base}/api/canvases", {"name": "边缘场景测试", "framework": "langchain"})
    cid, slug = c["id"], c["slug"]
    check("初始框架为 langchain", c["framework"] == "langchain")
    check("初始目录已创建", (PROJECTS / slug / "agent.json").exists(), slug)

    c2 = call("PATCH", f"{base}/api/canvases/{cid}", {"framework": "autogen"})
    kinds = {n["data"]["kind"] for n in c2["graph"]["nodes"]}
    check("切换到 autogen", c2["framework"] == "autogen", f"{len(kinds)} 种节点")
    check("架构图已重建为 AutoGen 节点", "autogen_group_chat" in kinds, ",".join(sorted(kinds)))
    spec = json.loads((PROJECTS / slug / "agent.json").read_text(encoding="utf-8"))
    check("落盘的 agent.json 同步了框架", spec["framework"] == "autogen")
    check("agent.py 已按框架生成", "AutoGen" in (PROJECTS / slug / "agent.py").read_text(encoding="utf-8"))

    print("\n[B] 改名（目录同步）")
    c3 = call("PATCH", f"{base}/api/canvases/{cid}", {"name": "改过名的画布"})
    new_slug = c3["slug"]
    check("slug 跟随新名字", new_slug == "改过名的画布", new_slug)
    check("旧目录已迁走", not (PROJECTS / slug).exists() or slug == new_slug)
    check("新目录存在", (PROJECTS / new_slug / "agent.json").exists())
    check("ROLE 文件保留", (PROJECTS / new_slug / "runner.py").exists())

    print("\n[C] 文件浏览")
    files = call("GET", f"{base}/api/canvases/{cid}/files")
    paths = {f["path"] for f in files["files"]}
    check("文件树可读", "agent.json" in paths and "nodes" in str(paths), f"{len(paths)} 个文件")
    node_files = [p for p in paths if p.startswith("nodes/")]
    check("节点文件齐全", len(node_files) == len(c3["graph"]["nodes"]), f"{len(node_files)} 个")
    f = call("GET", f"{base}/api/canvases/{cid}/file?path=" + urllib.request.quote("nodes/" + node_files[0][6:]))
    check("读取节点代码", len(f["content"]) > 10, node_files[0])

    print("\n[D] 校验与删除")
    bad = call("POST", f"{base}/api/canvases/{cid}/save", {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}})
    check("空画布也能保存（运行时会提示缺 input）", bad["ok"])
    call("DELETE", f"{base}/api/canvases/{cid}")
    check("删除后目录已清理", not (PROJECTS / new_slug).exists(), new_slug)
    remaining = call("GET", f"{base}/api/canvases")
    check("列表里不再有它", all(x["id"] != cid for x in remaining))

    print("\n结果：" + ("通过 ✅" if ok else "失败 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
