from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """入口：把用户输入交给下游。"""
    text = ctx.text.strip()
    if not text:
        raise ValueError("输入为空，请先在运行面板填写输入")
    ctx.log(f"收到输入：{len(text)} 字")
    return text
