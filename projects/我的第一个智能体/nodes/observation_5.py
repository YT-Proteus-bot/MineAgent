from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """观察：记录本轮动作的真实结果（工具返回 / 环境反馈）。"""
    obs = {
        "node": ctx.node_name,
        "input": ctx.input,
        "summary": ctx.llm(
            f"把工具返回结果压缩成 3 条以内的观察要点：\n{ctx.text}",
            system="只陈述事实，不推断。",
        ),
        "raw": ctx.text,
    }
    ctx.state.setdefault("observations", []).append(obs)
    ctx.emit("observation", {"summary": obs["summary"]})
    return obs
