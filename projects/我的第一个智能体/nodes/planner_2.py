from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """任务规划：把目标拆成有序步骤。"""
    return ctx.llm(
        f"目标：{ctx.text}\n\n请输出执行计划，每行一步，形如「1. ...」，只输出计划。",
        system="你是任务规划专家，计划必须可执行、有依赖顺序。",
    )
