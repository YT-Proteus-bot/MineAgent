"""批量跑一遍 14 张架构画布，输出每张的真实运行状态。"""
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


def main():
    canvases = [c for c in call("GET", "/api/canvases")
                if c["name"].startswith(("开源 ·", "闭源 ·"))]
    env = dict(os.environ)
    env.update(MOCK)
    env["PYTHONIOENCODING"] = "utf-8"

    rows = []
    for c in canvases:
        d = call("GET", f"/api/canvases/{c['id']}")
        slug = d.get("slug") or ""
        proj = ROOT / "projects" / slug
        if not (proj / "agent.py").exists():
            rows.append((c["name"], "✘", "项目未生成", 0))
            continue
        req_file = proj / "requirements.txt"
        deps = req_file.read_text(encoding="utf-8").split() if req_file.exists() else []
        started = time.time()
        try:
            r = subprocess.run([sys.executable, "agent.py", "--input", "整理周报要点"],
                               cwd=str(proj), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60, env=env)
            cost = time.time() - started
            if r.returncode == 0 and "run_end" in (r.stdout or ""):
                rows.append((c["name"], "✔", "跑通", cost))
            else:
                err = (r.stderr or "").strip().splitlines()
                tail = err[-1][:70] if err else "无输出"
                rows.append((c["name"], "✘", tail, cost))
        except subprocess.TimeoutExpired:
            rows.append((c["name"], "⏱", "超时 60s", 60))

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
