"""内置 AI 助手：用「用户中心」里配置的 key，回答使用中遇到的框架 / 编排问题。

和画布运行用的是同一套模型配置（orchestrator_*），但只做问答，不执行任何画布操作。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..db import get_conn, get_setting, now_iso
from ..security import decrypt

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class AssistantRequest(BaseModel):
    messages: List[ChatMessage] = Field(default_factory=list)
    context: Optional[Dict[str, Any]] = None


SYSTEM_PROMPT = """你是 MineAgent 的内置助手，一个熟悉 LLM Agent 工程化的工程师。

这个产品是一个可视化 Agent 编排画布：用户在画布上拖节点、连线、写节点代码，
点保存会把画布编译成一个独立的 Python Agent 项目，点运行会在本机真实执行。

你要做的是帮用户解决他们使用这个产品时遇到的问题，常见方向包括：
- 编排设计：ReAct / Plan-and-Execute / Goal / Reflexion 该怎么选，循环怎么收敛，
  supervisor 和 worker 怎么分工，什么环节该拆成独立节点。
- RAG 链路：文档切分粒度、混合检索与重排、上下文拼装、引用与评估。
- 运行报错：模型返回格式不对、key 或 base_url 配错、节点输出类型不匹配、
  循环打转、工具调用失败。
- 节点代码：每个节点就是一个 run(ctx) 函数，可用 ctx.llm / ctx.agent / ctx.tools /
  ctx.delegate / ctx.retrieve / ctx.rerank / ctx.delegate 等能力。
- 约束规则：入出口唯一性、可达性、分支出口、工具必须挂在 agent 下游等。

回答要求：
1. 先给结论，再给理由和具体做法；不要泛泛而谈。
2. 需要改代码时直接给出可粘贴的代码片段。
3. 用户没说清楚时，先问一个最关键的问题再动手，不要一次问一堆。
4. 不要编造这个产品没有的功能；不确定就说“这个功能目前没有”。
5. 用中文回答。"""


def _runtime_cfg() -> Dict[str, Any]:
    return {
        "provider": get_setting("orchestrator_provider", "openai"),
        "base_url": get_setting("orchestrator_base_url", "") or "https://api.openai.com/v1",
        "model": get_setting("orchestrator_model", "") or "gpt-4o-mini",
        "api_key": decrypt(get_setting("orchestrator_api_key_cipher", "")),
    }


def _endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/") or "https://api.openai.com/v1"
    if base.endswith("/chat/completions"):
        return base
    if not base.endswith("/v1") and "/v1" not in base:
        base += "/v1"
    return base + "/chat/completions"


def _context_text(ctx: Optional[Dict[str, Any]]) -> str:
    if not ctx:
        return ""
    lines: List[str] = ["\n\n## 当前画布上下文"]
    if ctx.get("canvas"):
        c = ctx["canvas"]
        lines.append(f"- 画布：{c.get('name')}（框架 {c.get('framework')}，"
                     f"{c.get('node_count')} 个节点 / {c.get('edge_count')} 条连线）")
    nodes = ctx.get("nodes") or []
    if nodes:
        brief = "、".join(f"{n.get('label')}({n.get('kind')})" for n in nodes[:24])
        lines.append(f"- 节点：{brief}")
    violations = ctx.get("violations") or []
    if violations:
        lines.append("- 约束未通过：")
        for v in violations[:6]:
            lines.append(f"  · [{v.get('level')}] {v.get('title')}：{v.get('message')}")
    last_run = ctx.get("last_run")
    if last_run:
        lines.append(f"- 最近一次运行：{last_run}")
    if ctx.get("selected"):
        s = ctx["selected"]
        lines.append(f"- 当前选中节点：{s.get('label')}（{s.get('kind')} / {s.get('name')}）")
    return "\n".join(lines)


@router.get("/status")
def assistant_status():
    cfg = _runtime_cfg()
    return {
        "ready": bool(cfg["api_key"]),
        "model": cfg["model"],
        "base_url": cfg["base_url"],
        "hint": "" if cfg["api_key"] else "还没配置 key，去右上角「用户中心」填一个就能用",
    }


# --------------------------------------------------------------------------- #
# 历史对话：每次「新对话」都会把上一段存下来，不再像以前那样直接丢掉
# --------------------------------------------------------------------------- #
def _chat_brief(row) -> Dict[str, Any]:
    try:
        msgs = json.loads(row["messages"] or "[]")
    except Exception:  # noqa: BLE001
        msgs = []
    return {
        "id": row["id"],
        "title": row["title"] or (msgs[0]["content"][:30] if msgs else "新对话"),
        "message_count": len(msgs),
        "updated_at": row["updated_at"],
        "created_at": row["created_at"],
    }


@router.get("/chats")
def list_chats(limit: int = 50):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM assistant_chats ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_chat_brief(r) for r in rows]


@router.get("/chats/{chat_id}")
def get_chat(chat_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM assistant_chats WHERE id = ?", (chat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "对话不存在")
    try:
        msgs = json.loads(row["messages"] or "[]")
    except Exception:  # noqa: BLE001
        msgs = []
    return {"id": row["id"], "title": row["title"], "messages": msgs,
            "updated_at": row["updated_at"]}


class SaveChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(default_factory=list)
    chat_id: Optional[str] = None
    title: str = ""
    canvas_id: str = ""


@router.post("/chats")
def save_chat(payload: SaveChatRequest):
    """保存一轮对话：给了 chat_id 就续写，没有就新建一条。"""
    msgs = [{"role": m.role, "content": m.content} for m in payload.messages]
    if not msgs:
        return {"ok": True, "id": payload.chat_id or "", "skipped": True}
    title = (payload.title or "").strip()
    if not title:
        first_user = next((m for m in msgs if m["role"] == "user"), None)
        title = ((first_user or msgs[0])["content"] or "")[:40] or "新对话"
    ts = now_iso()
    with get_conn() as conn:
        existing = None
        if payload.chat_id:
            existing = conn.execute(
                "SELECT id FROM assistant_chats WHERE id = ?", (payload.chat_id,)
            ).fetchone()
        if existing:
            conn.execute(
                "UPDATE assistant_chats SET messages = ?, title = ?, updated_at = ? WHERE id = ?",
                (json.dumps(msgs, ensure_ascii=False), title, ts, payload.chat_id),
            )
            return {"ok": True, "id": payload.chat_id, "title": title}
        chat_id = uuid.uuid4().hex[:16]
        conn.execute(
            "INSERT INTO assistant_chats(id,title,messages,canvas_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (chat_id, title, json.dumps(msgs, ensure_ascii=False),
             payload.canvas_id or "", ts, ts),
        )
    return {"ok": True, "id": chat_id, "title": title}


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM assistant_chats WHERE id = ?", (chat_id,))
    return {"ok": True}


@router.post("/chat")
async def assistant_chat(payload: AssistantRequest):
    cfg = _runtime_cfg()
    if not cfg["api_key"]:
        raise HTTPException(
            400,
            "还没有配置模型 key：点右上角「用户中心」，填 Base URL / 模型名 / API Key 即可",
        )
    if not payload.messages:
        raise HTTPException(400, "消息不能为空")

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT + _context_text(payload.context)}
    ]
    for m in payload.messages[-20:]:
        role = m.role if m.role in ("user", "assistant") else "user"
        messages.append({"role": role, "content": m.content})

    body = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 2048,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    url = _endpoint(cfg["base_url"])

    async def stream():
        yield "data: " + json.dumps({"event": "start", "model": cfg["model"]},
                                    ensure_ascii=False) + "\n\n"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
                async with client.stream("POST", url, json=body, headers=headers) as resp:
                    if resp.status_code >= 400:
                        detail = (await resp.aread()).decode("utf-8", "replace")[:400]
                        yield "data: " + json.dumps(
                            {"event": "error", "message": f"模型返回 {resp.status_code}：{detail}"},
                            ensure_ascii=False) + "\n\n"
                        return
                    async for raw in resp.aiter_lines():
                        line = (raw or "").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                            delta = obj["choices"][0]["delta"].get("content") or ""
                        except Exception:  # noqa: BLE001
                            continue
                        if delta:
                            yield "data: " + json.dumps(
                                {"event": "token", "text": delta}, ensure_ascii=False) + "\n\n"
        except httpx.HTTPError as exc:
            yield "data: " + json.dumps(
                {"event": "error", "message": f"请求模型失败：{exc}"}, ensure_ascii=False) + "\n\n"
            return
        yield "data: " + json.dumps({"event": "done"}, ensure_ascii=False) + "\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
