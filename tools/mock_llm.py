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


def reply_for(messages) -> str:
    prompt = ""
    for m in messages:
        if m.get("role") == "user":
            prompt = m.get("content") or ""
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
        content = reply_for(messages)
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
