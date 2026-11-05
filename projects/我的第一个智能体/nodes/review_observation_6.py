from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """观察复核：判断观察是否充分、可信，是否需要再执行一次。"""
    data = ctx.json_prompt(
        "复核下面的观察结果：是否足够支撑决策？是否与目标相关？是否可信？",
        schema={"sufficient": True, "reliable": True, "missing": ["..."],
                "next_action": "continue|retry|replan", "reason": ""},
        context=ctx.input,
    )
    ctx.state["review"] = data
    ctx.emit("review_observation", data)
    return data
