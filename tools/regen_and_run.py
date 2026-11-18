"""重新保存所有架构画布（触发重新生成项目），然后逐个跑一遍。"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
ROOT = pathlib.Path(__file__).resolve().parent.parent
MOCK = {"MINEAGENT_BASE_URL": "http://127.0.0.1:8012/v1",
        "MINEAGENT_MODEL": "mock-model", "MINEAGENT_API_KEY": "mock-key"}


def call(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def regenerate(canvases):
    print("重新生成项目…")
    for c in canvases:
        d = call("GET", f"/api/canvases/{c['id']}")
        g = d["graph"]
        call("POST", f"/api/canvases/{c['id']}/save", {
            "nodes": g["nodes"], "edges": g["edges"],
            "viewport": g["viewport"], "background": d["background"],
        })
        stale = "Agent(" in (ROOT / "projects" / (d.get("slug") or "") / "agent.py").read_text(encoding="utf-8") \
            if (ROOT / "projects" / (d.get("slug") or "") / "agent.py").exists() else False
        print(f"  {c['name']:32s} {'⚠ 仍是 CrewAI 代码' if stale else 'ok'}")


def run_all(canvases):
    env = dict(os.environ)
    env.update(MOCK)
    env["PYTHONIOENCODING"] = "utf-8"
    rows = []
    for c in canvases:
        d = call("GET", f"/api/canvases/{c['id']}")
        proj = ROOT / "projects" / (d.get("slug") or "")
        if not (proj / "agent.py").exists():
            rows.append((c["name"], "✘", "未生成", 0.0))
            continue
        started = time.time()
        try:
            r = subprocess.run([sys.executable, "agent.py", "--input", "整理周报要点"],
                               cwd=str(proj), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60, env=env)
            cost = time.time() - started
            if r.returncode == 0 and "run_end" in (r.stdout or ""):
                rows.append((c["name"], "✔", "跑通", cost))
            else:
                err = [x for x in (r.stderr or "").splitlines() if x.strip()]
                rows.append((c["name"], "✘", (err[-1][:70] if err else "无输出"), cost))
        except subprocess.TimeoutExpired:
            rows.append((c["name"], "⏱", "超时 60s", 60.0))
    return rows


def main():
    canvases = [c for c in call("GET", "/api/canvases")
                if c["name"].startswith(("开源 ·", "闭源 ·"))]
    regenerate(canvases)
    print()
    rows = run_all(canvases)
    print(f"{'画布':34s} {'状态':4s} {'耗时':>6s}  说明")
    print("-" * 96)
    ok = 0
    for name, status, note, cost in rows:
        ok += status == "✔"
        print(f"{name:34s} {status:4s} {cost:6.1f}s  {note}")
    print("-" * 96)
    print(f"跑通 {ok} / {len(rows)}")


if __name__ == "__main__":
    main()
