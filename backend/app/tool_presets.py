"""内置工具预设：给 tool 节点一个下拉清单，选中就填好代码。

每个预设包含：
- label / description：下拉与文档展示
- params：节点属性面板里可调的默认参数
- args：生成 @tool 函数时的参数签名
- preview：零依赖预览模式执行 run(ctx) 的代码
- native：生成 agent.py 里 @tool 函数体的代码（缩进 4 空格）

约定：native 代码里用到的变量名必须与 args 一致；参数默认值用 __XXX__ 占位，
由 codegen/native.py 在生成时替换成节点参数里的值。
"""
from __future__ import annotations

from typing import Any, Dict, List

TOOL_PRESETS: Dict[str, Dict[str, Any]] = {
    "http_get": {
        "label": "HTTP GET",
        "description": "抓取一个 URL 的文本（只读，超时 20 秒）。",
        "params": [{"key": "url", "label": "默认 URL", "default": ""}],
        "args": "url: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """HTTP GET：抓取一个 URL 的文本。"""
    url = ctx.params.get("url") or ctx.text.strip()
    if not url:
        raise ValueError("http_get 需要 URL")
    return ctx.fetch_text(url, limit=8000)
''',
        "native": '''    import urllib.request

    target = ("__URL__" or url).strip()
    if not target:
        raise ValueError("http_get 需要 URL")
    req = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")[:8000]
''',
    },
    "http_post": {
        "label": "HTTP POST",
        "description": "向一个 URL POST JSON，返回响应文本。",
        "params": [{"key": "url", "label": "默认 URL", "default": ""},
                   {"key": "body", "label": "默认 JSON", "default": "{}"}],
        "args": 'url: str, body: str = ""',
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """HTTP POST：向 URL POST JSON。"""
    url = ctx.params.get("url") or ctx.text.strip()
    body = ctx.params.get("body") or "{}"
    return ctx.http("POST", url, headers={"Content-Type": "application/json"}, data=body)
''',
        "native": '''    import json as _json
    import urllib.request

    target = ("__URL__" or url).strip()
    payload = body or "__BODY__" or "{}"
    req = urllib.request.Request(
        target,
        data=payload.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "MineAgent"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")[:8000]
''',
    },
    "web_search": {
        "label": "联网搜索",
        "description": "用 DuckDuckGo 搜索并返回摘要（需要 langchain-community）。",
        "params": [],
        "args": "query: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """联网搜索：返回前几条摘要。"""
    return ctx.search(ctx.text, limit=5)
''',
        "native": '''    from langchain_community.tools import DuckDuckGoSearchRun

    return DuckDuckGoSearchRun().run(query)
''',
    },
    "calculator": {
        "label": "计算器",
        "description": "安全地计算四则运算表达式（不执行任意代码）。",
        "params": [],
        "args": "expression: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """计算器：只支持 + - * / ** 与括号。"""
    import ast
    import operator

    text = (ctx.params.get("expression") or ctx.text).strip()
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}

    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp):
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return ops[type(node.op)](_eval(node.operand))
        raise ValueError("不支持的表达式")

    return str(_eval(ast.parse(text, mode="eval").body))
''',
        "native": '''    import ast
    import operator

    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}

    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp):
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return ops[type(node.op)](_eval(node.operand))
        raise ValueError("不支持的表达式")

    return str(_eval(ast.parse(expression, mode="eval").body))
''',
    },
    "current_time": {
        "label": "当前时间",
        "description": "返回服务器当前时间（ISO 格式）。",
        "params": [],
        "args": 'query: str = \"\"',
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """当前时间：ISO 8601。"""
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")
''',
        "native": '''    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")
''',
    },
    "read_file": {
        "label": "读文件",
        "description": "读取项目目录内的文本文件（默认 8000 字）。",
        "params": [{"key": "path", "label": "默认路径", "default": ""}],
        "args": "path: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """读文件：只允许项目目录内。"""
    target = ctx.params.get("path") or ctx.text.strip()
    if not target:
        raise ValueError("read_file 需要路径")
    return ctx.read_file(target)[:8000]
''',
        "native": '''    from pathlib import Path

    base = Path(__file__).resolve().parent
    target = ("__PATH__" or path).strip()
    if not target:
        raise ValueError("read_file 需要路径")
    resolved = (base / target).resolve()
    if base not in resolved.parents and resolved != base:
        raise PermissionError("只能读项目目录内的文件")
    return resolved.read_text(encoding="utf-8", errors="replace")[:8000]
''',
    },
    "sql_query": {
        "label": "SQL 查询",
        "description": "对项目内的 SQLite 执行只读查询。",
        "params": [{"key": "sql", "label": "默认 SQL", "default": "SELECT 1"}],
        "args": "sql: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """SQL 查询：只读。"""
    statement = ctx.params.get("sql") or ctx.text.strip()
    return ctx.query_sql(statement)
''',
        "native": '''    import sqlite3
    from pathlib import Path

    db_path = Path(__file__).resolve().parent / ".store.db"
    if not db_path.exists():
        raise FileNotFoundError("项目内还没有 .store.db，先运行一次或手动创建")
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()[:100]
        return str(rows)
    finally:
        conn.close()
''',
    },
    "json_query": {
        "label": "JSON 取值",
        "description": "从 JSON 文本里按 a.b.0.c 路径取值。",
        "params": [{"key": "path", "label": "默认路径", "default": ""}],
        "args": "data: str, path: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """JSON 取值：按 a.b.0 路径取。"""
    import json

    raw = ctx.params.get("data") or ctx.text
    path = ctx.params.get("path") or ""
    value = json.loads(raw) if isinstance(raw, str) else raw
    for part in [p for p in path.split(".") if p]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value
''',
        "native": '''    import json

    value = json.loads(data) if isinstance(data, str) else data
    for part in [p for p in (path or "").split(".") if p]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value
''',
    },
    "knowledge_search": {
        "label": "知识库检索",
        "description": "从项目 skills/docs/outputs 里召回片段（预览模式）。",
        "params": [],
        "args": "query: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """知识库检索：项目内文件召回。"""
    docs = ctx.retrieve(ctx.text, top_k=4, mode="hybrid")
    return ctx.build_context(docs, max_chars=3000)
''',
        "native": '''    from pathlib import Path

    base = Path(__file__).resolve().parent
    hits = []
    for folder in ("skills", "docs", "outputs"):
        for file in (base / folder).rglob("*"):
            if file.is_file() and file.suffix.lower() not in {".png", ".jpg", ".pyc"}:
                try:
                    text = file.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                if query.lower() in text.lower():
                    hits.append(f"[{file.relative_to(base)}] " + text[:800])
            if len(hits) >= 4:
                break
    return "\\n\\n".join(hits) or "（没有召回内容）"
''',
    },
    "pwsh": {
        "label": "PowerShell 命令",
        "description": "在本机执行一条 PowerShell 命令。",
        "params": [],
        "args": "command: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """执行 PowerShell 命令。"""
    result = ctx.shell(ctx.text, timeout=60)
    return (result.get("stdout") or "") + (result.get("stderr") or "")
''',
        "native": '''    import subprocess

    proc = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                          capture_output=True, text=True, timeout=60)
    return (proc.stdout + proc.stderr)[:8000]
''',
    },
    "bash": {
        "label": "Shell 命令",
        "description": "在本机执行一条 shell 命令（Windows 走 cmd，其他走 bash）。",
        "params": [],
        "args": "command: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """执行 shell 命令。"""
    result = ctx.shell(ctx.text, timeout=60)
    return (result.get("stdout") or "") + (result.get("stderr") or "")
''',
        "native": '''    import subprocess

    proc = subprocess.run(command, shell=True, capture_output=True,
                          text=True, timeout=60)
    return (proc.stdout + proc.stderr)[:8000]
''',
    },
    "read": {
        "label": "读文件（行范围）",
        "description": "按行读取项目内文本文件，支持 offset/limit。",
        "params": [],
        "args": "path: str, offset: int = 0, limit: int = 200",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """读文件：按行范围。"""
    return ctx.read_file(ctx.text)[:8000]
''',
        "native": '''    from pathlib import Path

    base = Path(__file__).resolve().parent
    target = (base / path).resolve()
    if base not in target.parents and target != base:
        raise PermissionError("只能读项目目录内的文件")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    kept = lines[offset:offset + limit] if limit else lines[offset:]
    return "\\n".join(kept)[:8000]
''',
    },
    "write": {
        "label": "写文件",
        "description": "把内容写入项目内的文件（自动建目录）。",
        "params": [],
        "args": "path: str, content: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """写文件：只允许项目目录内。"""
    return ctx.write_file(ctx.params.get("path") or "outputs/out.txt", ctx.text)
''',
        "native": '''    from pathlib import Path

    base = Path(__file__).resolve().parent
    target = (base / path).resolve()
    if base not in target.parents and target != base:
        raise PermissionError("只能写项目目录内的文件")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target.relative_to(base))
''',
    },
    "edit": {
        "label": "编辑文件（替换）",
        "description": "把文件里的 old 文本替换成 new（只替换第一处）。",
        "params": [],
        "args": "path: str, old: str, new: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """编辑文件：字符串替换。"""
    path = ctx.params.get("path") or ""
    text = ctx.read_file(path)
    old = ctx.params.get("old") or ""
    if old not in text:
        raise ValueError("文件里找不到要替换的内容")
    return ctx.write_file(path, text.replace(old, ctx.params.get("new") or "", 1))
''',
        "native": '''    from pathlib import Path

    base = Path(__file__).resolve().parent
    target = (base / path).resolve()
    if base not in target.parents and target != base:
        raise PermissionError("只能改项目目录内的文件")
    text = target.read_text(encoding="utf-8", errors="replace")
    if old not in text:
        raise ValueError("文件里找不到要替换的内容")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"已替换 {path}"
''',
    },
    "glob": {
        "label": "文件匹配（glob）",
        "description": "按 glob 模式列出项目内的文件。",
        "params": [],
        "args": "pattern: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """文件匹配：返回匹配到的相对路径。"""
    from pathlib import Path

    base = Path(__file__).resolve().parent
    hits = sorted(str(p.relative_to(base)) for p in base.glob(ctx.text) if p.is_file())
    return "\\n".join(hits[:200]) or "（没有匹配文件）"
''',
        "native": '''    from pathlib import Path

    base = Path(__file__).resolve().parent
    hits = sorted(str(p.relative_to(base)) for p in base.glob(pattern) if p.is_file())
    return "\\n".join(hits[:200]) or "（没有匹配文件）"
''',
    },
    "grep": {
        "label": "内容搜索（grep）",
        "description": "用正则搜索项目内文件内容，返回路径、行号和命中行。",
        "params": [],
        "args": "pattern: str, path: str = \".\"",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """内容搜索：正则匹配项目文件。"""
    import re
    from pathlib import Path

    base = Path(__file__).resolve().parent
    regex = re.compile(ctx.text)
    hits = []
    for file in base.rglob("*"):
        if not file.is_file() or file.suffix.lower() in {".png", ".jpg", ".pyc"}:
            continue
        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if regex.search(line):
                hits.append(f"{file.relative_to(base)}:{i}: {line.strip()[:160]}")
        if len(hits) >= 50:
            break
    return "\\n".join(hits[:50]) or "（没有匹配）"
''',
        "native": '''    import re
    from pathlib import Path

    base = Path(__file__).resolve().parent
    regex = re.compile(pattern)
    hits = []
    for file in (base / path).rglob("*"):
        if not file.is_file() or file.suffix.lower() in {".png", ".jpg", ".pyc"}:
            continue
        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if regex.search(line):
                hits.append(f"{file.relative_to(base)}:{i}: {line.strip()[:160]}")
        if len(hits) >= 50:
            break
    return "\\n".join(hits[:50]) or "（没有匹配）"
''',
    },
    "web_fetch": {
        "label": "网页抓取",
        "description": "抓取一个 URL 的正文文本（前 8000 字）。",
        "params": [],
        "args": "url: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """网页抓取：返回正文文本。"""
    return ctx.fetch_text(ctx.text, limit=8000)
''',
        "native": '''    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")[:8000]
''',
    },
    "todo_write": {
        "label": "写 TODO 列表",
        "description": "把待办列表写到项目根目录的 TODO.md。",
        "params": [],
        "args": "todos: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """写 TODO：落盘到 TODO.md。"""
    return ctx.write_file("TODO.md", ctx.text)
''',
        "native": '''    from pathlib import Path

    base = Path(__file__).resolve().parent
    path = base / "TODO.md"
    path.write_text(todos, encoding="utf-8")
    return str(path.relative_to(base))
''',
    },
    "create_goal": {
        "label": "创建目标",
        "description": "把目标写进项目内的 .goal.json。",
        "params": [],
        "args": "goal: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """创建目标：写入 .goal.json。"""
    import json

    data = {"goal": ctx.text, "status": "active", "history": []}
    ctx.write_file(".goal.json", json.dumps(data, ensure_ascii=False, indent=2))
    return json.dumps(data, ensure_ascii=False)
''',
        "native": '''    import json
    from pathlib import Path

    base = Path(__file__).resolve().parent
    path = base / ".goal.json"
    data = {"goal": goal, "status": "active", "history": []}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps(data, ensure_ascii=False)
''',
    },
    "get_goal": {
        "label": "读取目标",
        "description": "读取项目内 .goal.json 的对象与状态。",
        "params": [],
        "args": 'query: str = \"\"',
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """读取目标。"""
    return ctx.read_file(".goal.json")
''',
        "native": '''    from pathlib import Path

    path = Path(__file__).resolve().parent / ".goal.json"
    if not path.exists():
        return "（还没有目标）"
    return path.read_text(encoding="utf-8")
''',
    },
    "update_goal": {
        "label": "更新目标",
        "description": "更新目标状态并追加一条历史记录。",
        "params": [],
        "args": 'status: str, note: str = ""',
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """更新目标：追加历史。"""
    import json

    data = json.loads(ctx.read_file(".goal.json") or "{}")
    data["status"] = ctx.params.get("status") or "updated"
    data.setdefault("history", []).append({"status": data["status"]})
    ctx.write_file(".goal.json", json.dumps(data, ensure_ascii=False, indent=2))
    return json.dumps(data, ensure_ascii=False)
''',
        "native": '''    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent / ".goal.json"
    if not path.exists():
        raise FileNotFoundError("先用 create_goal 创建目标")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = status
    data.setdefault("history", []).append({"status": status, "note": note})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps(data, ensure_ascii=False)
''',
    },
    "present": {
        "label": "登记交付物",
        "description": "把产物路径登记到 .presented.json，返回登记结果。",
        "params": [],
        "args": "path: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """登记交付物。"""
    import json

    return ctx.write_file(".presented.json", json.dumps([ctx.text], ensure_ascii=False))
''',
        "native": '''    import json
    from pathlib import Path

    base = Path(__file__).resolve().parent
    record = base / ".presented.json"
    items = []
    if record.exists():
        try:
            items = json.loads(record.read_text(encoding="utf-8"))
        except Exception:
            items = []
    items.append(path)
    record.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"已登记交付物：{path}"
''',
    },
    "skill": {
        "label": "读取技能",
        "description": "从项目 skills/ 目录读取指定技能文件。",
        "params": [],
        "args": "name: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """读取技能文件。"""
    return ctx.skill(ctx.text)
''',
        "native": '''    from pathlib import Path

    base = Path(__file__).resolve().parent
    for candidate in (base / "skills" / name, base / "skills" / f"{name}.md", base / name):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")[:8000]
    return "（没有找到技能文件）"
''',
    },
    "working_directory": {
        "label": "工作目录",
        "description": "不带参数返回当前目录；带参数则切换过去。",
        "params": [],
        "args": 'path: str = \"\"',
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """工作目录：查看或切换。"""
    import os

    if not ctx.text.strip():
        return os.getcwd()
    os.chdir(ctx.text.strip())
    return os.getcwd()
''',
        "native": '''    import os
    from pathlib import Path

    if not path:
        return os.getcwd()
    target = Path(path).resolve()
    os.chdir(target)
    return str(target)
''',
    },
    "read_image": {
        "label": "读取图片信息",
        "description": "返回图片的文件大小与路径（不加载像素）。",
        "params": [],
        "args": "path: str",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """读取图片信息。"""
    from pathlib import Path

    target = Path(__file__).resolve().parent / ctx.text
    return f"{ctx.text}: {target.stat().st_size} bytes" if target.exists() else "（文件不存在）"
''',
        "native": '''    from pathlib import Path

    base = Path(__file__).resolve().parent
    target = (base / path).resolve()
    if not target.exists():
        raise FileNotFoundError(path)
    return f"{path}: {target.stat().st_size} bytes"
''',
    },
    "load_workspace_dependencies": {
        "label": "查看运行环境",
        "description": "返回 Python 解释器和 site-packages 路径。",
        "params": [],
        "args": 'query: str = \"\"',
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """查看运行环境。"""
    import site
    import sys

    paths = site.getsitepackages() if hasattr(site, "getsitepackages") else []
    return f"python={sys.executable}\\n" + "\\n".join(paths)
''',
        "native": '''    import site
    import sys

    paths = site.getsitepackages() if hasattr(site, "getsitepackages") else []
    return f"python={sys.executable}\\n" + "\\n".join(paths)
''',
    },
    "ask_user_question": {
        "label": "向用户提问",
        "description": "在命令行里向用户提问并返回回答；非交互环境返回提示。",
        "params": [],
        "args": 'question: str, options: str = ""',
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """向用户提问。"""
    import sys

    if not sys.stdin.isatty():
        return f"（非交互环境）问题：{ctx.text}"
    return input(f"{ctx.text} ")
''',
        "native": '''    import sys

    if not sys.stdin.isatty():
        return f"（非交互环境）问题：{question}"
    return input(f"{question} ")
''',
    },
    "propose_action": {
        "label": "提交待审批动作",
        "description": "把动作写进 .actions.json 等待审批，返回提交结果。",
        "params": [],
        "args": 'action: str, detail: str = ""',
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """提交待审批动作。"""
    import json

    return ctx.write_file(".actions.json", json.dumps([{"action": ctx.text, "status": "pending"}], ensure_ascii=False))
''',
        "native": '''    import json
    from pathlib import Path

    base = Path(__file__).resolve().parent
    path = base / ".actions.json"
    items = []
    if path.exists():
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            items = []
    items.append({"action": action, "detail": detail, "status": "pending"})
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"已提交待审批动作：{action}"
''',
    },
    "office_convert": {
        "label": "Office 转 PDF",
        "description": "用 LibreOffice 把文档转成 PDF（需要本机装 soffice）。",
        "params": [],
        "args": "input_path: str, output_dir: str = \"outputs\"",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Office 转 PDF。"""
    import subprocess

    proc = subprocess.run(["soffice", "--headless", "--convert-to", "pdf",
                           "--outdir", "outputs", ctx.text],
                          capture_output=True, text=True, timeout=120)
    return (proc.stdout + proc.stderr)[:2000]
''',
        "native": '''    import subprocess
    from pathlib import Path

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["soffice", "--headless", "--convert-to", "pdf",
                           "--outdir", str(out), input_path],
                          capture_output=True, text=True, timeout=120)
    return (proc.stdout + proc.stderr)[:2000]
''',
    },
    "office_render": {
        "label": "Office 转图片",
        "description": "用 LibreOffice 把文档渲染成 PNG（需要本机装 soffice）。",
        "params": [],
        "args": "input_path: str, output_dir: str = \"outputs\"",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Office 转图片。"""
    import subprocess

    proc = subprocess.run(["soffice", "--headless", "--convert-to", "png",
                           "--outdir", "outputs", ctx.text],
                          capture_output=True, text=True, timeout=120)
    return (proc.stdout + proc.stderr)[:2000]
''',
        "native": '''    import subprocess
    from pathlib import Path

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["soffice", "--headless", "--convert-to", "png",
                           "--outdir", str(out), input_path],
                          capture_output=True, text=True, timeout=120)
    return (proc.stdout + proc.stderr)[:2000]
''',
    },
    "office_recalculate": {
        "label": "Office 重算公式",
        "description": "用 LibreOffice 重算表格公式并另存（需要本机装 soffice）。",
        "params": [],
        "args": "input_path: str, output_dir: str = \"outputs\"",
        "preview": '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Office 重算公式。"""
    import subprocess

    proc = subprocess.run(["soffice", "--headless", "--convert-to", "xlsx",
                           "--outdir", "outputs", ctx.text],
                          capture_output=True, text=True, timeout=120)
    return (proc.stdout + proc.stderr)[:2000]
''',
        "native": '''    import subprocess
    from pathlib import Path

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["soffice", "--headless", "--convert-to", "xlsx",
                           "--outdir", str(out), input_path],
                          capture_output=True, text=True, timeout=120)
    return (proc.stdout + proc.stderr)[:2000]
''',
    },
}


# 每个内置工具的「一句话功能描述」：套用后写进节点说明，替掉通用模板文案
SUMMARY: Dict[str, str] = {
    "http_get": "用 urllib 以 GET 抓取 URL 文本，返回前 8000 字。",
    "http_post": "向 URL POST JSON 请求体，返回响应文本（前 8000 字）。",
    "web_search": "用 DuckDuckGo 搜索 query，返回前几条结果摘要。",
    "calculator": "解析并计算 + - * / ** 表达式，返回结果字符串。",
    "current_time": "返回服务器当前时间（ISO 8601，精确到秒）。",
    "read_file": "读取项目目录内的文本文件，返回前 8000 字。",
    "sql_query": "对项目内 .store.db 执行只读 SQL，返回前 100 行。",
    "json_query": "解析 JSON 文本，按 a.b.0 点路径取值。",
    "knowledge_search": "在 skills/docs/outputs 里按关键词召回，返回带来源的上下文。",
    "pwsh": "执行一条 PowerShell 命令并返回输出。",
    "bash": "执行一条 shell 命令并返回输出。",
    "read": "按行读取项目内文本文件。",
    "write": "把内容写入项目内文件。",
    "edit": "把文件里的 old 文本替换成 new。",
    "glob": "按 glob 模式列出项目内文件。",
    "grep": "用正则搜索项目文件内容，返回行号和命中行。",
    "web_fetch": "抓取 URL 正文文本，返回前 8000 字。",
    "todo_write": "把待办列表写到 TODO.md。",
    "create_goal": "把目标写进 .goal.json。",
    "get_goal": "读取 .goal.json 里的目标与状态。",
    "update_goal": "更新目标状态并追加历史。",
    "present": "把产物路径登记到 .presented.json。",
    "skill": "从 skills/ 读取指定技能文件。",
    "working_directory": "查看或切换当前工作目录。",
    "read_image": "返回图片文件大小与路径。",
    "load_workspace_dependencies": "返回 Python 解释器和 site-packages 路径。",
    "ask_user_question": "在命令行向用户提问并返回回答。",
    "propose_action": "把动作写进 .actions.json 等待审批。",
    "office_convert": "用 LibreOffice 把文档转成 PDF。",
    "office_render": "用 LibreOffice 把文档渲染成 PNG。",
    "office_recalculate": "用 LibreOffice 重算表格公式。",
}


def list_presets() -> List[Dict[str, Any]]:
    """给前端下拉用的清单（不含代码）。"""
    out = []
    for pid, spec in TOOL_PRESETS.items():
        out.append({
            "id": pid,
            "label": spec["label"],
            "description": spec["description"],
            "summary": SUMMARY.get(pid, spec["description"]),
            "params": spec.get("params") or [],
            "args": spec.get("args") or "query: str",
        })
    return out


def get_summary(preset: str) -> str:
    return SUMMARY.get(preset, "")


def get_preset(preset: str) -> Dict[str, Any] | None:
    return TOOL_PRESETS.get(preset)
