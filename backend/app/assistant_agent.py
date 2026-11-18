"""AI 助手的 Agent 循环。

一轮对话里可以连续调用多次工具：查画布 → 查节点说明 → 提出修改 → 再查一步确认。
读工具直接执行并把结果回填给模型；写工具不执行，转成「待确认」事件推给前端。

只依赖 httpx 和标准库，不引入 langchain —— 这个循环足够简单，自己写更好控制。
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from . import assistant_tools as tools

MAX_STEPS = 6
MAX_TOOL_RESULT_CHARS = 4000

EventFn = Callable[[Dict[str, Any]], Awaitable[None]]


def _endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/") or "https://api.deepseek.com/v1"
    if base.endswith("/chat/completions"):
        return base
    if not base.endswith("/v1") and "/v1" not in base:
        base += "/v1"
    return base + "/chat/completions"


def _trim(result: Any) -> str:
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "\n…（结果过长已截断）"
    return text


async def run_agent(
    *,
    system_prompt: str,
    messages: List[Dict[str, Any]],
    canvas_id: str,
    context: Optional[Dict[str, Any]],
    cfg: Dict[str, Any],
    on_event: EventFn,
    max_steps: int = MAX_STEPS,
) -> None:
    """跑完一轮 Agent 对话，过程中通过 on_event 推事件。"""
    url = _endpoint(cfg.get("base_url") or "")
    headers = {
        "Authorization": f"Bearer {cfg.get('api_key') or ''}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    convo: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    convo.extend(messages)

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
        for step in range(max_steps):
            body = {
                "model": cfg.get("model") or "deepseek-chat",
                "messages": convo,
                "temperature": 0.3,
                "max_tokens": 4096,
                "stream": True,
                "tools": tools.TOOL_SCHEMAS,
                "tool_choice": "auto",
            }
            text_parts: List[str] = []
            calls: Dict[int, Dict[str, str]] = {}

            try:
                async with client.stream("POST", url, json=body, headers=headers) as resp:
                    if resp.status_code >= 400:
                        detail = (await resp.aread()).decode("utf-8", "replace")[:400]
                        await on_event({"event": "error",
                                        "message": f"模型返回 {resp.status_code}：{detail}"})
                        return
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            text_parts.append(piece)
                            await on_event({"event": "token", "text": piece})
                        for call in delta.get("tool_calls") or []:
                            idx = int(call.get("index") or 0)
                            slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if call.get("id"):
                                slot["id"] = call["id"]
                            fn = call.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
            except httpx.HTTPError as exc:
                await on_event({"event": "error", "message": f"请求失败：{exc}"})
                return

            if not calls:
                # 没有工具调用：这一轮就是最终回答
                await on_event({"event": "done", "steps": step + 1})
                return

            # 有工具调用：把这一轮的文本和 tool_calls 都记进对话
            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            joined = "".join(text_parts).strip()
            assistant_msg["content"] = joined or None
            assistant_msg["tool_calls"] = [
                {"id": slot["id"] or f"call_{idx}", "type": "function",
                 "function": {"name": slot["name"],
                              "arguments": slot["arguments"] or "{}"}}
                for idx, slot in sorted(calls.items())
            ]
            convo.append(assistant_msg)

            for idx, slot in sorted(calls.items()):
                name = slot["name"] or ""
                try:
                    args = json.loads(slot["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                await on_event({"event": "tool_start", "tool": name,
                                "args": {k: v for k, v in args.items()
                                         if k in ("kind", "keyword", "query", "content")}})

                result = tools.execute(name, args, canvas_id=canvas_id, context=context)

                if result.get("__pending__"):
                    # 写工具：不执行，推给前端等确认
                    await on_event({"event": "pending", "tool": name,
                                    "payload": result.get("payload") or {}})
                    feedback = {
                        "status": "pending_confirmation",
                        "message": "操作已生成，等用户在界面上点确认后才生效。"
                                   "不要假设它已经执行成功。",
                    }
                    await on_event({"event": "tool_end", "tool": name,
                                    "summary": "已生成待确认操作"})
                else:
                    feedback = result
                    summary = (result.get("error") if isinstance(result, dict) and result.get("error")
                               else "完成")
                    await on_event({"event": "tool_end", "tool": name,
                                    "summary": str(summary)[:200]})

                convo.append({
                    "role": "tool",
                    "tool_call_id": slot["id"] or f"call_{idx}",
                    "content": _trim(feedback),
                })

        # 步数用完还没收敛
        await on_event({
            "event": "error",
            "message": f"工具调用超过 {max_steps} 步仍未给出最终回答，已停止。可以让我继续，或缩小问题范围。",
        })
