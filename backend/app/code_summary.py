"""从工具代码里生成一句话介绍。

优先取 docstring 的第一句；没有 docstring 时按代码里用到的能力做启发式判断。
纯静态、零依赖，不调用模型。
"""
from __future__ import annotations

import ast
import re

# 关键词 → 一句话功能描述（顺序即优先级）
_RULES = [
    ("urllib.request", "用 urllib 发起 HTTP 请求并返回响应文本。"),
    ("requests.", "用 requests 发起 HTTP 请求并返回响应。"),
    ("sqlite3", "连接 SQLite 执行 SQL 并返回结果。"),
    ("subprocess", "执行本地命令并返回输出。"),
    ("ctx.search", "调用联网搜索并返回结果摘要。"),
    ("ctx.fetch_text", "抓取网页正文。"),
    ("ctx.read_file", "读取项目内文件内容。"),
    ("ctx.write_file", "把内容写入项目内文件。"),
    ("ctx.retrieve", "从项目内知识库召回相关片段。"),
    ("ctx.query_sql", "执行只读 SQL 查询。"),
    ("ctx.llm", "调用大模型生成回答。"),
    ("ctx.agent", "交给内置 Agent 推理并返回结果。"),
    ("json.loads", "解析 JSON 数据。"),
    ("re.findall", "用正则从文本里抽取内容。"),
    ("re.search", "用正则匹配文本。"),
    ("datetime", "返回当前时间。"),
    ("math.", "做数值计算。"),
]

DEFAULT_SUMMARY = "自定义工具：执行节点里的 Python 逻辑。"


def _first_sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    line = text.splitlines()[0].strip()
    line = re.split(r"[。！？.!?]", line)[0].strip()
    return line[:80]


def summarize_code(code: str, fallback: str = DEFAULT_SUMMARY) -> str:
    """返回一句话介绍；code 为空时返回 fallback。"""
    code = (code or "").strip()
    if not code:
        return fallback
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None
    if tree is not None:
        doc = ast.get_docstring(tree)
        if not doc:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node)
                    if doc:
                        break
        summary = _first_sentence(doc or "")
        if summary and summary not in ("节点逻辑", "工具", "run"):
            return summary
    for token, text in _RULES:
        if token in code:
            return text
    return fallback
