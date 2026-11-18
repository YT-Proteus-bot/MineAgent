"""本地 Mock 模型服务：没有 API Key 也能把画布流程跑通。

启动：
    python tools/mock_llm.py --port 8012

然后在网页「用户中心」里填：
    Base URL: http://127.0.0.1:8012/v1
    Model:    mock-model
    API Key:  mock
"""
from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def content_text(content) -> str:
    """取消息正文。

    新一点的 SDK（smolagents / openai-agents 等）发的是多模态数组：
    [{"type": "text", "text": "..."}]，这里统一摊平成字符串。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return "" if content is None else str(content)


def reply_for(messages) -> str:
    prompt = ""
    for m in messages:
        if m.get("role") == "user":
            prompt = content_text(m.get("content"))
    low = prompt.lower()
    if "只回答 true 或 false" in prompt or "only answer true or false" in low:
        return "false"
    if "final_answer" in prompt or "action_input" in prompt:
        return json.dumps({"thought": "已获得足够信息", "final_answer":
                           "【Mock 输出】这是本地 mock 模型生成的最终答案。"}, ensure_ascii=False)
    if '"score"' in prompt:
        return json.dumps({"score": 92, "reason": "结构完整"}, ensure_ascii=False)
    if '"subtasks"' in prompt:
        return json.dumps({"subtasks": [{"id": "s1", "title": "收集信息", "goal": "检索"},
                                        {"id": "s2", "title": "整理输出", "goal": "成稿"}]},
                          ensure_ascii=False)
    return "【Mock 输出】" + (prompt[:120].replace("\n", " ") or "空输入")


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            data = {}
        messages = data.get("messages") or []
        tools = data.get("tools") or []
        content = reply_for(messages)

        # 支持 function calling：带 tools 且还没拿到工具结果时，先发起一次工具调用。
        # 这样 agent 节点 + 工具节点（web_search / http_request 等）的链路能被真跑验证。
        # agent 节点默认用流式，所以两种响应模式都要支持。
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if tools and not has_tool_result:
            fn = (tools[0].get("function") or {})
            fn_name = fn.get("name", "tool")
            call_args = json.dumps({"query": "MineAgent"})
            if data.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    for chunk in (
                        {"choices": [{"index": 0, "delta": {"role": "assistant"},
                                      "finish_reason": None}]},
                        {"choices": [{"index": 0, "delta": {"tool_calls": [{
                            "index": 0, "id": "call_mock_1", "type": "function",
                            "function": {"name": fn_name, "arguments": call_args}}]},
                            "finish_reason": None}]},
                        {"choices": [{"index": 0, "delta": {},
                                      "finish_reason": "tool_calls"}]},
                    ):
                        payload = {"id": "chatcmpl-mock",
                                   "object": "chat.completion.chunk",
                                   "model": data.get("model", "mock-model"), **chunk}
                        self.wfile.write(
                            ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n")
                            .encode("utf-8"))
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            self._send({
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": data.get("model", "mock-model"),
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_mock_1",
                            "type": "function",
                            "function": {"name": fn_name, "arguments": call_args},
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20,
                          "total_tokens": 30},
            })
            return

        # 支持 SSE 流式，方便测内置助手和流式节点
        if data.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for i in range(0, len(content), 12):
                    chunk = {"id": "chatcmpl-mock", "object": "chat.completion.chunk",
                             "choices": [{"index": 0, "delta": {"content": content[i:i + 12]},
                                          "finish_reason": None}]}
                    self.wfile.write(
                        ("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.02)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        self._send({
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": data.get("model", "mock-model"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        })

    def do_GET(self):  # noqa: N802
        self._send({"object": "list", "data": [{"id": "mock-model", "object": "model"}]})

    def log_message(self, fmt, *args):  # noqa: A003
        print(f"[mock] {fmt % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock LLM 已启动：http://{args.host}:{args.port}/v1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
