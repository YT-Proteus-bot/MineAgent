from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """条件路由：返回 "true" 或 "false" 决定走哪条出边。"""
    question = ctx.params.get("question") or "该请求是否需要调用工具？"
    verdict = ctx.llm(
        f"判别问题：{question}\n待判内容：{ctx.text}\n只回答 true 或 false。",
        system="你只输出 true 或 false，不要解释。",
    ).strip().lower()
    branch = "true" if verdict.startswith("true") else "false"
    ctx.emit("route", {"branch": branch})
    return branch
