"""AI 助手的长期记忆（按画布隔离）。

存什么：这张画布相关的约定、踩过的坑、做过的决定。
检索：字符二元组重叠度打分——不需要向量模型，几十条记忆足够用。

不入库的东西：运行日志、节点清单这些每次都能实时取到的，不算「记忆」。
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List

from .db import get_conn, now_iso

KINDS = ("note", "preference", "pitfall", "decision")


def _bigrams(text: str) -> set:
    s = re.sub(r"\s+", "", text or "").lower()
    if len(s) <= 1:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _score(query: str, content: str) -> float:
    q = _bigrams(query)
    if not q:
        return 0.0
    c = _bigrams(content)
    return len(q & c) / len(q)


def add(canvas_id: str, content: str, kind: str = "note") -> Dict[str, Any]:
    """写一条记忆。内容几乎重复时更新而不是新增。"""
    text = (content or "").strip()
    if not text:
        raise ValueError("记忆内容为空")
    if not canvas_id:
        raise ValueError("记忆必须属于一张画布")
    kind = kind if kind in KINDS else "note"
    ts = now_iso()
    with get_conn() as conn:
        # 近重复就去重：保留新的那条
        for row in conn.execute(
                "SELECT id, content FROM assistant_memories WHERE canvas_id = ?",
                (canvas_id,)).fetchall():
            if _score(text, row["content"]) > 0.85 or _score(row["content"], text) > 0.85:
                conn.execute(
                    "UPDATE assistant_memories SET content = ?, kind = ?, updated_at = ? "
                    "WHERE id = ?", (text, kind, ts, row["id"]))
                return {"ok": True, "id": row["id"], "updated": True}
        mem_id = uuid.uuid4().hex[:16]
        conn.execute(
            "INSERT INTO assistant_memories(id,canvas_id,kind,content,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (mem_id, canvas_id, kind, text, ts, ts))
    return {"ok": True, "id": mem_id, "updated": False}


def list_all(canvas_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM assistant_memories WHERE canvas_id = ? "
            "ORDER BY updated_at DESC LIMIT ?", (canvas_id, limit)).fetchall()
    return [dict(r) for r in rows]


def search(canvas_id: str, query: str, limit: int = 6) -> List[Dict[str, Any]]:
    """按相关度取记忆。没有相关度时退化成最近几条，保证有上下文。"""
    rows = list_all(canvas_id, limit=200)
    if not rows:
        return []
    if not (query or "").strip():
        return rows[:limit]
    scored = []
    for row in rows:
        s = _score(query, row.get("content") or "")
        if s > 0:
            scored.append((s, row))
    if not scored:
        return rows[:min(limit, 3)]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{**row, "score": round(s, 3)} for s, row in scored[:limit]]


def remove(mem_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM assistant_memories WHERE id = ?", (mem_id,))
    return cur.rowcount > 0


def clear(canvas_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM assistant_memories WHERE canvas_id = ?",
                           (canvas_id,))
    return cur.rowcount


def render_for_prompt(memories: List[Dict[str, Any]]) -> str:
    """把记忆渲染成提示词里的一段。"""
    if not memories:
        return ""
    lines = ["\n\n## 这张画布的长期记忆（之前对话里记下的）"]
    for mem in memories:
        kind = mem.get("kind") or "note"
        label = {"preference": "偏好", "pitfall": "坑", "decision": "决定"}.get(kind, "备注")
        lines.append(f"- [{label}] {mem.get('content')}")
    return "\n".join(lines)
