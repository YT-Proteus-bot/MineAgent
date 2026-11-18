"""验证同步冲突检测：本地改动检测、sync-status、force 覆盖。

不依赖 GitHub：local-changed 的判断发生在拉取远端之前，
所以直接伪造 remote_slug / base_graph_hash 就能测。
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


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

    # 造一张临时画布
    status, canvas = call("POST", "/api/canvases", {"name": "冲突检测临时画布", "framework": "langchain"})
    if status != 200:
        print(f"创建画布失败: {canvas}")
        return
    cid = canvas["id"]
    print(f"临时画布: {cid}\n")

    try:
        # 1) 没绑定远端时，sync-status 应该是 linked=false
        status, res = call("GET", f"/api/community/sync-status/{cid}")
        check("未绑定时 linked=false", status == 200 and res.get("linked") is False,
              f"status={status}")

        # 2) 从外部写库，伪造"已同步过第 2 版 + 基线哈希"
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from backend.app import community
        from backend.app.db import get_conn

        # 基线哈希必须用库里存的那份 graph 来算，否则和 sync-status 里算的对不上
        with get_conn() as conn:
            stored = conn.execute("SELECT graph FROM canvases WHERE id = ?", (cid,)).fetchone()
        stored_graph = json.loads(stored["graph"])
        base_hash = community.graph_hash(stored_graph)
        with get_conn() as conn:
            conn.execute(
                "UPDATE canvases SET remote_slug=?, remote_rev=?, base_graph_hash=? WHERE id=?",
                ("demo-template", 2, base_hash, cid),
            )
        check("已伪造同步基线（第 2 版）", True, f"hash={base_hash}")

        # 3) 内容没变时，sync-status 的 local_changed 应为 false
        status, res = call("GET", f"/api/community/sync-status/{cid}")
        print(f"     sync-status 返回：{json.dumps(res, ensure_ascii=False)[:220]}")
        check("内容未变 local_changed=false", res.get("local_changed") is False,
              f"link={res.get('linked')} err={res.get('error', '')[:40]}")

        # 4) 本地改一笔（加个节点），local_changed 应变成 true
        _, detail = call("GET", f"/api/canvases/{cid}")
        graph = detail["graph"]
        nodes = list(graph["nodes"])
        nodes.append({
            "id": "n_new", "type": "agent", "position": {"x": 900, "y": 0},
            "data": {"kind": "llm", "label": "新节点", "name": "llm_new",
                     "description": "", "code": "", "language": "python", "params": {}},
        })
        _, saved = call("POST", f"/api/canvases/{cid}/save", {
            "nodes": nodes, "edges": graph["edges"],
            "viewport": graph["viewport"], "background": graph["background"],
        })
        check("本地改动已保存", saved.get("ok") is True)

        status, res = call("GET", f"/api/community/sync-status/{cid}")
        check("改动后 local_changed=true", res.get("local_changed") is True,
              f"local={res.get('local_hash')} base={base_hash}")

        # 5) 拉取更新时应该被拦（409 local-changed）
        status, res = call("POST", "/api/community/load", {
            "slug": "demo-template", "mode": "update", "canvas_id": cid,
        })
        detail = res.get("detail") if isinstance(res, dict) else {}
        is_conflict = status == 409 and isinstance(detail, dict) and detail.get("kind") == "local-changed"
        check("拉取被拦为 local-changed", is_conflict,
              f"status={status} kind={(detail or {}).get('kind') if isinstance(detail, dict) else ''}")

        if isinstance(detail, dict):
            check("冲突信息带 canvas_id", detail.get("canvas_id") == cid)
            check("冲突信息带 local_hash", bool(detail.get("local_hash")))

        # 6) force 应该跳过检查（随后因远端模板不存在而失败，但不再是 409 冲突）
        status, res = call("POST", "/api/community/load", {
            "slug": "demo-template", "mode": "update", "canvas_id": cid, "force": True,
        })
        not_conflict = not (status == 409 and isinstance(res.get("detail"), dict))
        check("force 跳过冲突检查", not_conflict, f"status={status}")

    finally:
        call("DELETE", f"/api/canvases/{cid}")
        print(f"\n临时画布已删除")

    print(f"\n通过 {passed} / {passed + failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
