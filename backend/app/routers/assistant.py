"""内置 AI 助手（Agent 形态）：带工具调用、短期/长期记忆、上下文压缩。

和画布运行用的是同一套模型配置（orchestrator_*）。
读工具自动执行；改画布这类写操作只生成「待确认」动作，等用户点确认。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import assistant_memory
from ..assistant_agent import run_agent
from ..db import get_conn, get_setting, now_iso
from ..security import decrypt

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


def _sse(obj: Dict[str, Any]) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False, default=str) + "\n\n"


class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class AssistantRequest(BaseModel):
    messages: List[ChatMessage] = Field(default_factory=list)
    context: Optional[Dict[str, Any]] = None
    canvas_id: str = ""
    # 更早对话的压缩摘要（前端在消息变长后生成并带回来）
    summary: str = ""


class CompressRequest(BaseModel):
    messages: List[ChatMessage] = Field(default_factory=list)
    canvas_id: str = ""


RUNTIME_PROMPT = """

## 你的运行方式（Agent）

你现在是一个能调用工具的 Agent，不只是聊天。

工具使用原则：
1. 回答前先确认事实：涉及画布结构就调 `get_canvas`，涉及节点能力就调 `get_node_doc` /
   `list_node_types`，涉及「为什么跑不起来」就调 `get_run_log`。不要凭印象猜节点 id。
2. 改画布用 `apply_ops`（局部改动）或 `apply_canvas`（整张重做）。这两个工具**不会立刻生效**，
   会生成一张待用户确认的卡片。你可以在同一轮里继续做别的检查，但不要假设它已经生效、
   也不要对用户说「已经改好了」。
3. 用户明确表达了偏好/约定，或你们确认了一个非显然的结论时，用 `remember` 记下来。
4. `run_canvas` 会真的消耗模型额度，只在用户明确要求运行或验证时调。
5. 最多 6 步工具调用。信息够了就直接回答，不要为了用工具而用工具。
6. **项目配置也能改**：`update_service`（服务设置）、`update_model`（对话模型）、
   `set_mode`（推理模式）、`switch_framework`（框架）、`upsert_provider`
   （向量模型 / 向量库 / 数据源）。改之前先用 `get_config` 看现状，别猜。
   - `switch_framework` 会**重建整张架构图**，是破坏性操作，只有用户明确说「换成 XX 框架」
     才调；如果只是在讨论，不要调。
   - 这些配置类工具同样只生成待确认卡片，不会立刻生效。
7. **你改不了 API Key**。`update_model` 只动 provider / base_url / model / 参数；
   `upsert_provider` 只写非密钥字段。需要 Key 时明确告诉用户去「画布配置」里自己填，
   不要假装已经配好了。
8. **还原开源智能体**：用户说「还原 / 复刻 / 按 XX 的架构做」时，
   先 `list_architectures` 查有没有收录；有就 `get_architecture` 拿到行为指纹和拓扑，
   再 `apply_architecture` 生成。没有收录的，直接说「这个项目还没收录」，
   然后基于 `get_node_doc` 现场设计，并说明哪些行为可能对不上。
   **不要假装还原了自己不认识的架构。**
9. **从源码画图**：用户给 GitHub 地址、上传源码包、或给本地路径时，先 `scan_source`
   拿静态扫描结果（目录、依赖、import、类与函数、prompt/工具线索），再据它画。
   规则：
   - 画布只能表达「节点 + 连线」，源码里的类/函数要**归并**成节点，不要一个类一个节点
   - 扫描结果里没有的模块不要臆造；不确定就说「扫描没覆盖到」
   - 扫描只给线索不给结论，架构判断由你做，但要说明依据哪几个文件
"""


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


CANVAS_GUIDE = """

## 你还能直接生成画布

当用户说「搭一个 / 生成 / 帮我设计 / 改成」某类 Agent 流程时，除了用文字讲清思路，
在回答的最后给出一个 ```canvas 代码块，内容是一张完整画布的 JSON：

```canvas
{
  "nodes": [
    {"key": "n1", "kind": "input", "label": "输入"},
    {"key": "n2", "kind": "agent", "label": "助理", "params": {"mode": "react", "max_steps": 6}},
    {"key": "n3", "kind": "output", "label": "输出"}
  ],
  "edges": [
    {"source": "n1", "target": "n2"},
    {"source": "n2", "target": "n3"}
  ]
}
```

硬性规则（不满足会被约束检查拦下）：
1. `kind` 必须来自下面的节点清单，不要编造类型。
2. 有且只有一个 `input`，至少一个 `output`。
3. 每个节点都要能从 input 到达，也都要能走到 output；不允许孤立节点。
4. 分支节点（`router` / `condition`）的两条出边都要写，用 `"branch": "true"` / `"false"` 区分。
5. 有环时必须有一个能收敛的出口，否则会死循环。
6. `tool` 节点的入边必须从某个 agent 连出来（工具是 agent 调用的，不是独立步骤）。
7. 节点代码默认按类型自动补齐；只有确实需要特殊逻辑时才在节点里加 `"code"` 字段，
   它的内容是一个完整的 `def run(ctx): ...` 函数。
8. 先用文字说明这张图怎么跑、每个节点做什么，再给 canvas 块。
9. 用户是在**替换**当前画布，所以给出的是完整的一张图，不是增量补丁。

### 可用节点类型
"""

_CANVAS_GUIDE_CACHE: str = ""


OPS_GUIDE = """

## 修改现有画布（增量操作）

如果用户是在**当前画布上做局部改动**（加/删节点、改参数、改某个节点的代码、
改连线、挪位置），不要重画整张图，改给一个 ```ops 代码块，内容是操作数组：

```ops
[
  {"op": "add_node", "key": "k1", "kind": "rag_retriever", "label": "检索",
   "params": {"top_k": 6}},
  {"op": "connect", "source": "n2", "target": "k1"},
  {"op": "connect", "source": "k1", "target": "n4"},
  {"op": "update_node", "id": "n4", "params": {"max_steps": 8}},
  {"op": "set_code", "id": "n4", "code": "def run(ctx):\\n    return ctx.llm(ctx.text)"},
  {"op": "move_node", "id": "n3", "x": 700, "y": 260},
  {"op": "relayout"}
]
```

操作清单：

| op | 必填 | 说明 |
| --- | --- | --- |
| `add_node` | `kind` | `key` 供本次其它操作引用；可选 `label` `name` `params` `code` `x` `y` |
| `remove_node` | `id` | 相关连线会一起删掉 |
| `update_node` | `id` | 可改 `label` `name` `params`（**合并**，不是覆盖） |
| `set_code` | `id` `code` | `code` 必须是完整的 `def run(ctx):` 函数 |
| `connect` | `source` `target` | 端点可以是节点 id 或本次 `add_node` 的 key；`branch` 填 `true`/`false` |
| `disconnect` | `source` `target` | 删掉指定连线 |
| `move_node` | `id` `x` `y` | 画布坐标 |
| `relayout` | — | 让整张图按流程自动重排，位置乱的时候用 |

规则：
1. 节点 id 必须用上面上下文里给出的真实 id（形如 `n1`、`n2`），不要自己编。
2. 一次只改用户要求的部分，不要顺手动别的节点。
3. 改完用文字说明改了哪几处，再给 ops 块。

**走哪条路：**
- 「搭一个 / 重新设计 / 换成某某架构」→ 用 ```canvas 给完整画布（整张替换）
- 「加一个 / 删掉 / 把 A 接到 B / 改一下某节点 / 挪一下 / 重新排一下」→ 用 ```ops 做增量
"""


def _canvas_guide() -> str:
    """节点清单按 registry 动态生成，避免提示词和实际类型对不上。"""
    global _CANVAS_GUIDE_CACHE
    if _CANVAS_GUIDE_CACHE:
        return _CANVAS_GUIDE_CACHE
    from ..node_registry import NODE_TYPES
    lines = []
    current = ""
    for node in NODE_TYPES:
        cat = node.get("category") or ""
        if cat != current:
            current = cat
            lines.append(f"\n【{cat}】")
        lines.append(f"- {node['kind']}：{node.get('label') or ''}")
    _CANVAS_GUIDE_CACHE = CANVAS_GUIDE + OPS_GUIDE + "\n".join(lines) + "\n"
    return _CANVAS_GUIDE_CACHE


def _runtime_cfg() -> Dict[str, Any]:
    return {
        "provider": get_setting("orchestrator_provider", "deepseek"),
        "base_url": get_setting("orchestrator_base_url", "") or "https://api.deepseek.com/v1",
        "model": get_setting("orchestrator_model", "") or "deepseek-chat",
        "api_key": decrypt(get_setting("orchestrator_api_key_cipher", "")),
    }


def _endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/") or "https://api.deepseek.com/v1"
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
        lines.append("- 节点（id / 名称 / 类型）：")
        for n in nodes[:40]:
            lines.append(f"  · {n.get('id')} / {n.get('label')} / {n.get('kind')}")
    edges = ctx.get("edges") or []
    if edges:
        pairs = "、".join(
            f"{e.get('source')}→{e.get('target')}" + (f"[{e.get('branch')}]" if e.get("branch") else "")
            for e in edges[:50])
        lines.append(f"- 连线：{pairs}")
    violations = ctx.get("violations") or []
    if violations:
        lines.append("- 约束未通过：")
        for v in violations[:6]:
            lines.append(f"  · [{v.get('level')}] {v.get('title')}：{v.get('message')}")
    last_run = ctx.get("last_run")
    if last_run:
        lines.append(f"- 最近一次运行结果：{last_run}")
    run_log = ctx.get("run_log") or []
    if run_log:
        lines.append("- 最近一次运行的执行过程（按时间顺序）：")
        for item in run_log[-60:]:
            stamp = str(item.get("at") or "")[-8:]
            name = item.get("node") or ""
            kind = item.get("event") or ""
            extra = ""
            if item.get("duration_ms") is not None:
                extra = f" {item['duration_ms']}ms"
            if item.get("message"):
                extra += f" {item['message']}"
            elif item.get("output"):
                extra += f" 输出={item['output']}"
            lines.append(f"  · [{stamp}] {kind} {name}{extra}".rstrip())
    if ctx.get("selected"):
        s = ctx["selected"]
        lines.append(f"- 当前选中节点：{s.get('id')} / {s.get('label')}"
                     f"（{s.get('kind')} / {s.get('name')}）")
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
def list_chats(limit: int = 50, canvas_id: str = ""):
    """对话列表。传 canvas_id 就只返回这张画布的对话。

    每张画布有自己的对话，避免把别的画布的上下文带进来。
    """
    with get_conn() as conn:
        if canvas_id:
            rows = conn.execute(
                "SELECT * FROM assistant_chats WHERE canvas_id = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (canvas_id, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM assistant_chats ORDER BY updated_at DESC LIMIT ?",
                (limit,)).fetchall()
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
            "summary": row["summary"] or "", "updated_at": row["updated_at"]}


class SaveChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(default_factory=list)
    chat_id: Optional[str] = None
    title: str = ""
    canvas_id: str = ""
    # 早前对话的压缩摘要，跟着对话一起存，刷新后还能用
    summary: str = ""


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
                "SELECT id, canvas_id FROM assistant_chats WHERE id = ?",
                (payload.chat_id,)).fetchone()
        # 对话属于某张画布；chat_id 和画布对不上时不能续写，
        # 否则会把 A 画布的对话内容写到 B 画布上
        if existing and payload.canvas_id and (
                existing["canvas_id"] or "") != payload.canvas_id:
            existing = None
        if existing:
            conn.execute(
                "UPDATE assistant_chats SET messages = ?, title = ?, summary = ?, "
                "updated_at = ? WHERE id = ?",
                (json.dumps(msgs, ensure_ascii=False), title,
                 payload.summary or "", ts, payload.chat_id),
            )
            return {"ok": True, "id": payload.chat_id, "title": title}
        chat_id = uuid.uuid4().hex[:16]
        conn.execute(
            "INSERT INTO assistant_chats(id,title,messages,canvas_id,summary,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (chat_id, title, json.dumps(msgs, ensure_ascii=False),
             payload.canvas_id or "", payload.summary or "", ts, ts),
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

    canvas_id = (payload.canvas_id or "").strip()

    # 长期记忆：按这一轮的用户问题检索这张画布存过的记忆
    last_user = ""
    for m in reversed(payload.messages):
        if m.role == "user":
            last_user = m.content or ""
            break
    memories = assistant_memory.search(canvas_id, last_user, limit=6) if canvas_id else []

    system_prompt = (
        SYSTEM_PROMPT
        + RUNTIME_PROMPT
        + _canvas_guide()
        + assistant_memory.render_for_prompt(memories)
        + _context_text(payload.context)
    )
    if payload.summary:
        system_prompt += f"\n\n## 早前对话的摘要\n{payload.summary}"

    history = [
        {"role": (m.role if m.role in ("user", "assistant") else "user"),
         "content": m.content}
        for m in payload.messages[-20:]
    ]

    async def stream():
        yield _sse({"event": "start", "model": cfg["model"]})
        queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()

        async def emit(evt: Dict[str, Any]) -> None:
            await queue.put(evt)

        async def runner() -> None:
            try:
                await run_agent(
                    system_prompt=system_prompt,
                    messages=history,
                    canvas_id=canvas_id,
                    context=payload.context,
                    cfg=cfg,
                    on_event=emit,
                )
            except Exception as exc:  # noqa: BLE001
                await emit({"event": "error", "message": f"Agent 执行失败：{exc}"})
            finally:
                await queue.put({"event": "__end__"})

        task = asyncio.create_task(runner())
        try:
            while True:
                evt = await queue.get()
                if evt.get("event") == "__end__":
                    break
                yield _sse(evt)
        finally:
            await task

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
# 上下文压缩：对话变长后把早期内容折成一段摘要
# --------------------------------------------------------------------------- #
@router.post("/compress")
async def compress_chat(payload: CompressRequest):
    """把较早的对话压成摘要，只保留最近 10 条。

    摘要会随下次请求的 `summary` 字段带回，替代被折掉的原文。
    """
    msgs = payload.messages or []
    keep = 10
    if len(msgs) <= keep + 4:
        return {"ok": True, "summary": "", "kept": len(msgs), "dropped": 0}

    older = msgs[:-keep]
    cfg = _runtime_cfg()
    if not cfg["api_key"]:
        raise HTTPException(400, "还没有配置模型 key")

    transcript = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'}：{m.content[:400]}" for m in older)
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system",
             "content": "把下面这段对话压缩成一份要点摘要，供后续对话继续使用。"
                        "保留：用户的目标与约束、已确认的结论、待办事项、画布当前状态的关键变化。"
                        "不要保留客套话和重复内容。用中文，分条，300 字以内。"},
            {"role": "user", "content": transcript[:12000]},
        ],
        "temperature": 0.2,
        "max_tokens": 800,
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}",
               "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
            resp = await client.post(_endpoint(cfg["base_url"]), json=body, headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(502, f"摘要生成失败：{resp.status_code} {resp.text[:200]}")
            data = resp.json()
            summary = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"摘要生成失败：{exc}") from exc

    return {"ok": True, "summary": summary.strip(), "kept": keep,
            "dropped": len(older)}


# --------------------------------------------------------------------------- #
# 长期记忆（按画布）
# --------------------------------------------------------------------------- #
@router.get("/memories")
def list_memories(canvas_id: str):
    if not canvas_id:
        raise HTTPException(400, "缺少 canvas_id")
    return {"ok": True, "memories": assistant_memory.list_all(canvas_id)}


@router.post("/memories")
def add_memory(payload: Dict[str, Any]):
    canvas_id = str(payload.get("canvas_id") or "")
    content = str(payload.get("content") or "")
    if not canvas_id or not content.strip():
        raise HTTPException(400, "缺少 canvas_id 或 content")
    try:
        result = assistant_memory.add(canvas_id, content,
                                      str(payload.get("kind") or "note"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **result}


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str):
    if not assistant_memory.remove(memory_id):
        raise HTTPException(404, "记忆不存在")
    return {"ok": True}


@router.delete("/memories")
def clear_memories(canvas_id: str):
    if not canvas_id:
        raise HTTPException(400, "缺少 canvas_id")
    return {"ok": True, "removed": assistant_memory.clear(canvas_id)}
