from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """观察格式化：把多轮观察整理成结构化上下文。"""
    obs = ctx.state.get("observations", [])
    if not obs and isinstance(ctx.input, list):
        obs = ctx.input
    lines = []
    for i, item in enumerate(obs, 1):
        summary = item.get("summary") if isinstance(item, dict) else str(item)
        lines.append(f"{i}. {summary}")
    text = ctx.params.get("header", "## 已有观察\n") + "\n".join(lines)
    return {"formatted": text, "count": len(lines), "raw": obs}
