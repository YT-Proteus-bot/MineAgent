"""把默认背景从透明迁移为纸白，并调整网格颜色。"""
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
db = root / "backend" / "data" / "mineagent.db"
backup = db.with_name(f"mineagent.db.bak-{datetime.now():%Y%m%d-%H%M%S}")
shutil.copy2(db, backup)
print("backup:", backup.name)

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
rows = conn.execute("select id, name, background, graph from canvases").fetchall()
changed = []
for row in rows:
    bg = json.loads(row["background"] or "{}")
    if not bg:
        continue
    touched = False
    if not bg.get("color") and not bg.get("image"):
        bg["color"] = "#f8fafc"
        touched = True
    if str(bg.get("grid_color") or "") in ("", "#1d2740"):
        bg["grid_color"] = "#c9d1de"
        touched = True
    if not touched:
        continue
    graph = json.loads(row["graph"] or "{}")
    graph["background"] = bg
    conn.execute(
        "UPDATE canvases SET background = ?, graph = ? WHERE id = ?",
        (json.dumps(bg, ensure_ascii=False), json.dumps(graph, ensure_ascii=False), row["id"]),
    )
    changed.append(row["name"] or row["id"])

conn.commit()
print("changed:", changed)
