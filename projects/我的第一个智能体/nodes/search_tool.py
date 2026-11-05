from runtime_sdk import NodeContext


def run(ctx: NodeContext, **kwargs):
    """工具节点：被 agent 节点调用时 kwargs 为模型给出的参数。

    直接连在流程中时也会作为普通节点执行一次。
    """
    query = kwargs.get("query") or ctx.params.get("query") or ctx.text
    ctx.log(f"tool 执行：{query}")
    # TODO: 在这里写真正的工具逻辑
    return {"tool": ctx.params.get("name", "tool"), "query": query, "result": ""}
