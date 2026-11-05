from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """带工具循环的 Agent（ReAct）。

    画布中「连到本节点输入」的 tool 子图会自动注入 ctx.tools。
    """
    system = ctx.params.get("system") or "你是一个能自主使用工具的智能体。"
    return ctx.agent(
        task=ctx.text,
        tools=ctx.tools,
        system=system,
        max_steps=ctx.params.get("max_steps", 6),
    )
