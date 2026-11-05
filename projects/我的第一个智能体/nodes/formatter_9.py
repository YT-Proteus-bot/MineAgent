from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """格式化：把结果整理成指定格式（markdown / json / table）。"""
    fmt = ctx.params.get("format", "markdown")
    return ctx.llm(
        f"把下面内容转成 {fmt} 格式，只输出结果本身：\n{ctx.text}",
        system="你是格式化工具，不做内容增删。",
    )
