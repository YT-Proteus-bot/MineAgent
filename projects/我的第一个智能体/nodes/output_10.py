from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """出口：终止流程并返回最终答案给用户。"""
    answer = ctx.text
    ctx.emit("final", {"answer": answer})
    return answer
