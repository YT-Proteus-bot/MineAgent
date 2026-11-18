"""验证画布下拉的远端同步信息：绑定的模板名、是否有新版本、更新按钮的数据来源。"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "backend" / "data" / "mineagent.db"


def call(method: str, path: str, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw}


def main():
    passed = failed = 0

    def check(name: str, ok: bool, extra: str = ""):
        nonlocal passed, failed
        print(f"  {'✔' if ok else '✘'} {name}{(' — ' + extra) if extra else ''}")
        if ok:
            passed += 1
        else:
            failed += 1

    status, canvas = call("POST", "/api/canvases", {"name": "同步信息临时画布", "framework": "langchain"})
    if status != 200:
        print(f"创建画布失败: {canvas}")
        return 1
    cid = canvas["id"]
    print(f"临时画布: {cid}\n")

    try:
        sys.path.insert(0, str(ROOT))
        from backend.app import community

        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        stored = conn.execute("SELECT graph FROM canvases WHERE id = ?", (cid,)).fetchone()
        base_hash = community.graph_hash(json.loads(stored["graph"]))
        # 伪造"从公共库拉了 demo-template 第 2 版"
        conn.execute(
            "UPDATE canvases SET remote_slug=?, remote_rev=?, remote_lib=?, remote_name=?, "
            "base_graph_hash=? WHERE id=?",
            ("demo-template", 2, "public", "演示模板", base_hash, cid),
        )
        conn.commit()
        conn.close()
        check("已伪造绑定（public / demo-template / 第 2 版）", True)

        # 1) 画布列表要带上远端字段
        status, items = call("GET", "/api/canvases")
        mine = next((x for x in items if x["id"] == cid), None)
        check("列表带 remote_slug", bool(mine and mine.get("remote_slug") == "demo-template"))
        check("列表带 remote_name", bool(mine and mine.get("remote_name") == "演示模板"))
        check("列表带 remote_lib", bool(mine and mine.get("remote_lib") == "public"))

        # 2) sync-overview 要覆盖这张画布
        status, ov = call("GET", "/api/community/sync-overview")
        item = next((x for x in (ov.get("items") or []) if x["canvas_id"] == cid), None)
        check("sync-overview 收录该画布", item is not None)
        if item:
            # 远端模板读不到时用 slug 兜底，所以这里只要求"有个能显示的名字"
            check("返回可显示的模板名", bool(item.get("remote_name")),
                  str(item.get("remote_name")))
            check("本地版本正确", item.get("local_rev") == 2)
            # 远端模板不存在时 remote_rev=0，按"没有更新"处理，不该打扰用户
            check("远端读不到时不算有更新", item.get("remote_changed") is False,
                  f"remote_rev={item.get('remote_rev')}")
            check("本地未改动 local_changed=false", item.get("local_changed") is False)

        # 3) 本地改一笔后，sync-overview 的 local_changed 应变 true
        status, detail = call("GET", f"/api/canvases/{cid}")
        graph = detail["graph"]
        nodes = list(graph["nodes"]) + [{
            "id": "n_x", "type": "agent", "position": {"x": 500, "y": 0},
            "data": {"kind": "llm", "label": "新节点", "name": "llm_x",
                     "description": "", "code": "", "language": "python", "params": {}},
        }]
        call("POST", f"/api/canvases/{cid}/save", {
            "nodes": nodes, "edges": graph["edges"],
            "viewport": graph["viewport"], "background": graph["background"],
        })
        status, ov = call("GET", "/api/community/sync-overview")
        item = next((x for x in (ov.get("items") or []) if x["canvas_id"] == cid), None)
        check("本地改动后 local_changed=true", bool(item and item.get("local_changed")),
              f"local_changed={item.get('local_changed') if item else None}")

        # 4) 点「更新」会被冲突检测拦下（本地有改动）
        status, res = call("POST", "/api/community/load", {
            "slug": "demo-template", "mode": "update", "canvas_id": cid,
        })
        d = res.get("detail") if isinstance(res, dict) else {}
        check("更新被拦为 local-changed", status == 409 and isinstance(d, dict) and d.get("kind") == "local-changed",
              f"status={status}")

    finally:
        call("DELETE", f"/api/canvases/{cid}")
        print("\n临时画布已删除")

    print(f"\n通过 {passed} / {passed + failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
