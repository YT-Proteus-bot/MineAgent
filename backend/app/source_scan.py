"""从源码静态扫描出架构线索。

只做「读代码能确定的事」：目录结构、依赖声明、模块间 import、类与函数、
prompt 片段、工具定义。归纳成节点图交给模型做（模型擅长，静态分析不擅长）。

刻意不做的：执行代码、装依赖、读超过 200KB 的文件、下钻 node_modules。
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".venv", "venv", "env", "site-packages", ".tox", "coverage", ".idea",
    ".vscode", "assets", "static", "public", "docs", "examples", "tests",
    "test", "__tests__", "fixtures", "migrations",
}
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".go", ".rs",
            ".java", ".kt", ".rb", ".cs", ".php"}
DEP_FILES = {"requirements.txt", "pyproject.toml", "package.json", "Pipfile",
             "setup.py", "setup.cfg", "go.mod", "Cargo.toml", "pom.xml"}
PROMPT_HINT = re.compile(r"(你是|您是一名|You are|You're an?|system prompt|系统提示)",
                        re.IGNORECASE)
TOOL_HINT = re.compile(
    r"(@tool\b|@function_tool\b|StructuredTool|Tool\(|"
    r"\"type\"\s*:\s*\"function\"|function_call|tool_choice|@tool\s*\()")
MAX_FILES = 1500
MAX_FILE_BYTES = 200_000
MAX_DEPTH = 7

# 排序优先级：核心目录往前排，脚本/构建/示例往后排。
# 不排序的话，遍历顺序会让 scripts/ 把 400 个扫描名额占满，真正的 core 一个都进不来。
_CORE_DIR = re.compile(
    r"(^|/)(src|source|apps?|packages?|core|lib|agent|agents|runtime|server|"
    r"backend|services?|handlers?|tools)(/|$)", re.IGNORECASE)
_SIDE_DIR = re.compile(
    r"(^|/)(scripts?|build|out|dist|docs?|examples?|benchmarks?|fixtures?|"
    r"migrations?|e2e|specs?)(/|$)", re.IGNORECASE)


def _priority(rel: str) -> tuple:
    """越小越先扫：非旁路目录 > 核心目录 > 浅 > 路径短。"""
    side = 1 if _SIDE_DIR.search(rel) else 0
    core = 0 if _CORE_DIR.search(rel) else 1
    depth = rel.count("/")
    return (side, core, depth, len(rel))


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _walk(root: Path) -> List[Path]:
    out: List[Path] = []
    stack = [(root, 0)]
    while stack and len(out) < MAX_FILES:
        current, depth = stack.pop()
        if depth > MAX_DEPTH:
            continue
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name.lower() in SKIP_DIRS or entry.name.startswith("."):
                    continue
                stack.append((entry, depth + 1))
            elif entry.is_file():
                out.append(entry)
                if len(out) >= MAX_FILES:
                    break
    return out


def _snippet(text: str, pattern: re.Pattern, limit: int = 6,
             min_len: int = 12) -> List[str]:
    """抓出含关键词的短片段，用来给模型看「它怎么说话/怎么定义工具」。

    min_len 是行长度下限：prompt 片段太短没信息量，但 `@tool` 这种本身
    就是强信号，所以工具线索用更低的阈值。
    """
    found: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) < min_len:
            continue
        if pattern.search(stripped):
            found.append(stripped[:180])
            if len(found) >= limit:
                break
    return found


def _scan_python(path: Path, rel: str, text: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {"path": rel, "imports": [], "classes": [], "functions": [],
                            "lines": text.count("\n") + 1}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return info
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            info["imports"].extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            info["imports"].append(node.module.split(".")[0])
        elif isinstance(node, ast.ClassDef):
            info["classes"].append([node.name, len(node.body)])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info["functions"].append(node.name)
    info["imports"] = sorted(set(info["imports"]))
    # 类太大时只留前 20 个，避免摘要爆掉
    info["classes"] = [[n, c] for n, c in info["classes"][:20]]
    info["functions"] = info["functions"][:40]
    return info


def _scan_js(rel: str, text: str) -> Dict[str, Any]:
    imports = set()
    for match in re.finditer(
            r"""(?:from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))""", text):
        mod = match.group(1) or match.group(2) or ""
        if mod:
            imports.add(mod.lstrip("./").split("/")[0] or mod)
    # 只认大写开头的类名：`class of` 这种是匹配到关键字了，会污染结果
    classes = re.findall(r"\bclass\s+([A-Z][\w$]*)", text)
    functions = re.findall(
        r"\b(?:function\s+([A-Za-z_$][\w$]*)|const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\()",
        text)
    names = [a or b for a, b in functions]
    return {"path": rel, "imports": sorted(imports)[:30],
            "classes": [[c, 0] for c in classes[:20]],
            "functions": names[:40], "lines": text.count("\n") + 1}


def _deps(root: Path, files: List[Path]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for path in files:
        if path.name not in DEP_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            continue
        names: List[str] = []
        if path.name == "package.json":
            try:
                data = json.loads(text)
                names = sorted((data.get("dependencies") or {}).keys())
                names += sorted((data.get("devDependencies") or {}).keys())
            except json.JSONDecodeError:
                pass
        elif path.name == "go.mod":
            names = re.findall(r"^\s+([\w./-]+)\s+v[\d.]+", text, re.M)[:40]
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.match(r"[\"']?([A-Za-z0-9_.\-]+)", line)
                if match:
                    names.append(match.group(1))
        if names:
            out[path.name] = names[:50]
    return out


def _tree_text(root: Path, depth: int = 3, limit: int = 80) -> str:
    lines: List[str] = []

    def walk(path: Path, level: int, prefix: str = "") -> None:
        if len(lines) >= limit or level > depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except OSError:
            return
        shown = [e for e in entries
                 if not (e.is_dir() and (e.name.lower() in SKIP_DIRS
                                         or e.name.startswith(".")))]
        for entry in shown[:24]:
            if len(lines) >= limit:
                return
            mark = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{entry.name}{mark}")
            if entry.is_dir():
                walk(entry, level + 1, prefix + "  ")

    walk(root, 0)
    return "\n".join(lines)


def scan(root: Path) -> Dict[str, Any]:
    """扫描一个源码目录，返回给模型看的结构化摘要。"""
    root = root.resolve()
    all_files = _walk(root)
    code_files = [f for f in all_files if f.suffix.lower() in CODE_EXT]
    # 核心目录优先，避免 scripts/ 之类把扫描名额吃光
    code_files.sort(key=lambda p: _priority(_rel(p, root)))
    scan_list = code_files[:400] or all_files[:200]

    modules: List[Dict[str, Any]] = []
    prompts: List[Dict[str, str]] = []
    tool_hints: List[Dict[str, str]] = []
    languages: Dict[str, int] = {}
    entrypoints: List[str] = []

    for path in scan_list:
        rel = _rel(path, root)
        suffix = path.suffix.lower()
        languages[suffix] = languages.get(suffix, 0) + 1
        if path.name in ("main.py", "agent.py", "app.py", "__main__.py", "index.js",
                         "index.ts", "main.ts", "main.go", "server.py", "run.py"):
            entrypoints.append(rel)
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                modules.append({"path": rel, "skipped": "文件过大"})
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if suffix == ".py":
            modules.append(_scan_python(path, rel, text))
        elif suffix in CODE_EXT:
            modules.append(_scan_js(rel, text))
        else:
            modules.append({"path": rel})

        if len(prompts) < 8:
            for line in _snippet(text, PROMPT_HINT, limit=2):
                prompts.append({"path": rel, "line": line})
        if len(tool_hints) < 8:
            for line in _snippet(text, TOOL_HINT, limit=2, min_len=4):
                tool_hints.append({"path": rel, "line": line})

    return {
        "root": root.name,
        "file_count": len(all_files),
        "code_file_count": len(code_files),
        "languages": dict(sorted(languages.items(), key=lambda kv: -kv[1])[:8]),
        "entrypoints": entrypoints[:12],
        "dependencies": _deps(root, all_files),
        "tree": _tree_text(root),
        "modules": modules[:120],
        "prompts": prompts[:8],
        "tool_hints": tool_hints[:8],
        "truncated": len(code_files) > len(scan_list),
    }
