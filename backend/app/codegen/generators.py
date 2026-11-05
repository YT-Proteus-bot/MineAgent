"""画布 → 独立 Agent 项目的代码生成器。"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..config import PROJECTS_DIR
from ..framework_templates import FRAMEWORK_INDEX
from ..node_registry import get_node_type
from .native import render_agent_full

RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"

REQUIREMENTS = {
    # langchain 1.x：旧的 AgentExecutor / create_react_agent 已移除，改用 create_agent
    "langchain": "langchain>=1.0\nlanggraph>=1.0\nlangchain-openai>=1.0\nlangchain-core>=1.0\n",
    "autogen": "autogen-agentchat>=0.4.0\nautogen-ext[openai]>=0.4.0\n",
    "crewai": "crewai>=0.60.0\n",
}


def slugify(name: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name or "").strip(" ._")
    s = re.sub(r"\s+", "_", s)
    return s[:60] or "canvas"


def unique_slug(base: str, exists=lambda s: False) -> str:
    slug = slugify(base)
    if not exists(slug):
        return slug
    i = 2
    while exists(f"{slug}_{i}"):
        i += 1
    return f"{slug}_{i}"


def _py_name(name: str, used: set, fallback: str) -> str:
    s = re.sub(r"\W", "_", name or "", flags=re.UNICODE).strip("_")
    if not s or not re.match(r"[A-Za-z_\u4e00-\u9fff]", s):
        s = fallback
    base, i = s, 2
    while s.lower() in used:
        s = f"{base}_{i}"
        i += 1
    used.add(s.lower())
    return s


# --------------------------------------------------------------------------- #
# 生成 agent.json
# --------------------------------------------------------------------------- #
def _node_org(raw: Any) -> Dict[str, Any]:
    """组织关系：上级 nodeId、下级与平级 nodeId 列表。"""
    if not isinstance(raw, dict):
        return {}

    def _ids(value: Any) -> List[str]:
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value if v]
        return []

    return {
        "superior": str(raw.get("superior") or ""),
        "subordinates": _ids(raw.get("subordinates")),
        "peers": _ids(raw.get("peers")),
    }


def _node_model(raw: Any) -> Optional[Dict[str, Any]]:
    """节点级模型：只留连接信息，api key 用环境变量名引用，绝不写明文。"""
    if not isinstance(raw, dict):
        return None
    cfg = {k: raw[k] for k in ("provider", "base_url", "model", "temperature", "max_tokens")
           if raw.get(k) not in (None, "")}
    env = raw.get("api_key_env")
    if env:
        cfg["api_key_env"] = env
    return cfg or None


def build_spec(name: str, slug: str, framework: str, graph: Dict[str, Any]) -> Dict[str, Any]:
    used: set = set()
    nodes = []
    for idx, node in enumerate(graph.get("nodes", []), 1):
        data = node.get("data") or {}
        kind = data.get("kind") or "llm"
        meta = get_node_type(kind)
        node_name = _py_name(data.get("name") or "", used, f"{kind}_{idx}")
        nodes.append({
            "id": node["id"],
            "kind": kind,
            "name": node_name,
            "label": data.get("label") or meta["label"],
            "description": data.get("description") or meta.get("description", ""),
            "file": f"{node_name}.py",
            "outputs": meta["outputs"],
            "params": data.get("params") or {},
            # 平台内零依赖预览时执行的就是这段 run(ctx)；
            # agent.py 里则是同一节点的框架原生写法
            "code": data.get("code") or meta.get("default_code", ""),
            "preview_code": data.get("preview_code") or meta.get("default_code", ""),
            "code_touched": bool(data.get("code_touched")),
            "position": node.get("position") or {"x": 0, "y": 0},
            "org": _node_org(data.get("org")),
            "model": _node_model(data.get("model")),
        })
    edges = []
    for e in graph.get("edges", []):
        edges.append({
            "source": e["source"],
            "target": e["target"],
            "sourceHandle": e.get("sourceHandle"),
            "targetHandle": e.get("targetHandle"),
            "label": e.get("label"),
        })
    return {
        "name": name,
        "slug": slug,
        "framework": framework,
        "framework_label": FRAMEWORK_INDEX.get(framework, {}).get("label", framework),
        "nodes": nodes,
        "edges": edges,
        "max_visits": 8,
    }


# --------------------------------------------------------------------------- #
# 框架原生入口 agent.py
# --------------------------------------------------------------------------- #
_AGENT_PY_COMMON = '''"""__PROJECT_NAME__ · __FRAMEWORK_LABEL__ 入口

本文件由 MineAgent 根据画布自动生成，可以直接修改。
优先使用框架原生实现；若本机没装对应框架，会自动回退到项目自带的 runner.py。

用法：
    python agent.py --input "你的问题"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from runtime_sdk import NodeContext  # noqa: E402

SPEC = json.loads((HERE / "agent.json").read_text(encoding="utf-8"))
NODES = {n["id"]: n for n in SPEC["nodes"]}
EDGES = SPEC["edges"]
ROUTE_SIGNALS = {"true", "false", "loop", "exit", "yes", "no", "approve", "reject"}


def load_node_module(node_id):
    import importlib.util
    node = NODES[node_id]
    path = HERE / "nodes" / node["file"]
    spec = importlib.util.spec_from_file_location("ma_" + node_id, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call_node(node_id, payload, state):
    node = NODES[node_id]
    ctx = NodeContext(node_id=node_id, node_name=node["name"], kind=node["kind"],
                      params=node.get("params") or {}, payload=payload, state=state)
    return load_node_module(node_id).run(ctx)
'''

_AGENT_LANGGRAPH = _AGENT_PY_COMMON + '''

def run_native(user_input: str):
    from typing import Any, TypedDict
    from langgraph.graph import END, START, StateGraph

    class S(TypedDict, total=False):
        data: Any
        route: str
        state: dict

    shared = {"state": {}}

    def wrap(node_id):
        def fn(state: S) -> S:
            out = call_node(node_id, state.get("data"), shared["state"])
            if isinstance(out, str) and out.strip().lower() in ROUTE_SIGNALS:
                return {"data": state.get("data"), "route": out.strip().lower(),
                        "state": shared["state"]}
            return {"data": out, "route": "", "state": shared["state"]}
        return fn

    g = StateGraph(S)
    for nid, node in NODES.items():
        g.add_node(nid, wrap(nid))

    start = next((n["id"] for n in SPEC["nodes"] if n["kind"] == "input"), None)
    if start:
        g.add_edge(START, start)

    targets: dict = {}
    for e in EDGES:
        handle = e.get("sourceHandle")
        if handle:
            targets.setdefault(e["source"], {})[handle] = e["target"]
        else:
            g.add_edge(e["source"], e["target"])

    ends = [nid for nid in NODES if not any(e["source"] == nid for e in EDGES)]
    for nid in ends:
        if nid not in targets:
            g.add_edge(nid, END)

    for src, mapping in targets.items():
        def make_router(mapping=mapping):
            def route(state: S):
                val = (state.get("route") or "").strip().lower()
                if val in mapping:
                    return val
                return next(iter(mapping))
            return route
        g.add_conditional_edges(src, make_router(), mapping)

    app = g.compile()
    result = app.invoke({"data": user_input, "route": "", "state": {}})
    return result.get("data")


def main(user_input: str):
    try:
        out = run_native(user_input)
        print("")
        print("===== 最终结果 =====")
        print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return out
    except ImportError as exc:
        print(f"[提示] 未安装 LangGraph（{exc}），改用项目内置 runner。")
        from runner import GraphRunner
        runner = GraphRunner(SPEC)
        out = runner.run(user_input)
        print("")
        print("===== 最终结果 =====")
        print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return out
'''

_AGENT_AUTOGEN = _AGENT_PY_COMMON + '''

def _model_client():
    from autogen_ext.models.openai import OpenAIChatCompletionClient
    from runtime_sdk import load_config
    cfg = load_config()
    return OpenAIChatCompletionClient(
        model=cfg["model"], base_url=cfg.get("base_url"), api_key=cfg["api_key"],
        model_info={"vision": False, "function_calling": True, "json_output": True,
                    "family": "unknown", "structured_output": False},
    )


def run_native(user_input: str):
    import asyncio
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.teams import RoundRobinGroupChat

    members = [n for n in SPEC["nodes"]
               if n["kind"] in {"autogen_assistant", "autogen_tool_agent",
                                "worker", "supervisor", "llm", "agent"}]
    if not members:
        raise RuntimeError("画布中没有可用于 AutoGen 的 agent 节点")

    async def _run():
        client = _model_client()
        agents = []
        for n in members:
            params = n.get("params") or {}
            agents.append(AssistantAgent(
                name=n["name"][:32] or "agent",
                model_client=client,
                system_message=params.get("system_message")
                or params.get("role")
                or f"你是 {n['label']}，负责该环节的工作。",
            ))
        team = RoundRobinGroupChat(agents, max_turns=int(SPEC.get("max_visits", 4)) + 2)
        result = await team.run(task=user_input)
        await client.close()
        messages = getattr(result, "messages", [])
        return messages[-1].content if messages else ""

    return asyncio.run(_run())


def main(user_input: str):
    try:
        out = run_native(user_input)
    except Exception as exc:  # noqa: BLE001
        print(f"[提示] AutoGen 原生入口不可用（{exc}），改用项目内置 runner。")
        from runner import GraphRunner
        out = GraphRunner(SPEC).run(user_input)
    print("")
    print("===== 最终结果 =====")
    print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return out
'''

_AGENT_CREWAI = _AGENT_PY_COMMON + '''

def run_native(user_input: str):
    from crewai import Agent, Crew, Process, Task

    agent_nodes = [n for n in SPEC["nodes"]
                   if n["kind"] in {"crewai_agent", "worker", "supervisor", "llm", "agent"}]
    task_nodes = [n for n in SPEC["nodes"] if n["kind"] == "crewai_task"]
    if not agent_nodes:
        raise RuntimeError("画布中没有可用于 CrewAI 的 agent 节点")

    crew_agents = []
    for n in agent_nodes:
        p = n.get("params") or {}
        crew_agents.append(Agent(
            role=p.get("role") or n["label"],
            goal=p.get("goal") or "高质量完成分配的任务",
            backstory=p.get("backstory") or "你是经验丰富的专业人士。",
            verbose=False,
        ))

    crew_tasks = []
    for i, t in enumerate(task_nodes or agent_nodes):
        p = t.get("params") or {}
        owner = crew_agents[min(i, len(crew_agents) - 1)]
        crew_tasks.append(Task(
            description=p.get("description") or f"完成第 {i + 1} 阶段任务：{{input}}",
            expected_output=p.get("expected_output") or "结构化的最终交付物",
            agent=owner,
        ))
    if not crew_tasks:
        crew_tasks.append(Task(description="{input}", expected_output="最终答案", agent=crew_agents[0]))

    crew = Crew(agents=crew_agents, tasks=crew_tasks, process=Process.sequential, verbose=False)
    result = crew.kickoff(inputs={"input": user_input})
    return str(result)


def main(user_input: str):
    try:
        out = run_native(user_input)
    except Exception as exc:  # noqa: BLE001
        print(f"[提示] CrewAI 原生入口不可用（{exc}），改用项目内置 runner。")
        from runner import GraphRunner
        out = GraphRunner(SPEC).run(user_input)
    print("")
    print("===== 最终结果 =====")
    print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return out
'''

AGENT_PY = {
    "langchain": _AGENT_LANGGRAPH,
    "autogen": _AGENT_AUTOGEN,
    "crewai": _AGENT_CREWAI,
}

_MAIN_TAIL = '''

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", default="")
    args = parser.parse_args()
    text = args.input or sys.stdin.read()
    main(text)
'''


# --------------------------------------------------------------------------- #
# 写项目
# --------------------------------------------------------------------------- #
def generate_project(name: str, slug: str, framework: str, graph: Dict[str, Any],
                     model_config: Dict[str, Any]) -> Tuple[Path, List[str]]:
    project_dir = PROJECTS_DIR / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    nodes_dir = project_dir / "nodes"
    nodes_dir.mkdir(exist_ok=True)
    (project_dir / "skills").mkdir(exist_ok=True)
    (project_dir / "outputs").mkdir(exist_ok=True)

    spec = build_spec(name, slug, framework, graph)
    written: List[str] = []

    def write(rel: str, content: str) -> None:
        path = project_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(rel)

    write("agent.json", json.dumps(spec, ensure_ascii=False, indent=2))

    # 不再生成 nodes/*.py：节点代码内联在 agent.py 里，agent.json 也存了一份
    # 旧的 nodes 目录直接清掉，避免两份代码打架
    if nodes_dir.exists():
        for old in nodes_dir.glob("*.py"):
            old.unlink(missing_ok=True)
        try:
            nodes_dir.rmdir()
        except OSError:
            pass

    # skill 节点的内容单独落一个 md，方便用编辑器改
    for node, src in zip(spec["nodes"], graph.get("nodes", [])):
        data = src.get("data") or {}
        skill_text = (data.get("params") or {}).get("skill_text") or ""
        if node["kind"] == "skill" and str(skill_text).strip():
            write(f"skills/{node['name']}.md", str(skill_text).rstrip() + "\n")

    # 运行时
    for fname in ("runtime_sdk.py", "runner.py"):
        shutil.copyfile(RUNTIME_DIR / fname, project_dir / fname)
        written.append(fname)

    # 框架入口：一整个 agent.py，就是这份画布的框架原生代码
    agent_code, node_blocks = render_agent_full(spec, framework)
    write("agent.py", agent_code)

    # 把每个节点在 agent.py 里的代码块写回画布数据：
    # 网页上「代码逻辑」显示的就是这段，改的也是这段
    for node, src in zip(spec["nodes"], graph.get("nodes", [])):
        block = node_blocks.get(node["id"])
        data = src.setdefault("data", {})
        if block:
            data["code"] = block
        # 这是生成的版本，不是用户手改的，下次保存允许重新生成
        data["code_generated"] = True
        # 降级预览用的 run(ctx)：老画布没有就按节点类型补一份
        if not data.get("preview_code"):
            data["preview_code"] = get_node_type(node["kind"]).get("default_code", "")

    # 模型配置（不含 key）
    cfg = {
        "provider": model_config.get("provider", "deepseek"),
        "base_url": model_config.get("base_url") or "https://api.deepseek.com/v1",
        "model": model_config.get("model") or "deepseek-chat",
        "temperature": model_config.get("temperature", 0.3),
        "max_tokens": model_config.get("max_tokens", 2048),
        "api_key_env": "MINEAGENT_API_KEY",
    }
    write("config.json", json.dumps(cfg, ensure_ascii=False, indent=2))

    write("requirements.txt", REQUIREMENTS.get(framework, "# 无额外依赖（使用内置 runner）\n"))

    env_example = (
        "# 复制为 .env 并填入你的 key（网页上配置过的话可以不填）\n"
        "MINEAGENT_API_KEY=sk-xxxx\n"
        f"MINEAGENT_BASE_URL={cfg['base_url']}\n"
        f"MINEAGENT_MODEL={cfg['model']}\n"
    )
    write(".env.example", env_example)
    write(".gitignore",
          ".env\n.venv/\n.store.db\n__pycache__/\n*.pyc\n"
          "outputs/*\n!outputs/.gitkeep\n")

    # 空目录留占位文件，保证复制 / 打包 / git 之后目录结构不丢
    write("skills/.gitkeep", "# 技能文件（skill 节点的 skill.md）放这里\n")
    write("outputs/.gitkeep", "# 运行产物会写到这个目录\n")

    # 一键运行脚本：拿到这个文件夹就能跑，不需要记命令
    write("run.ps1", "\ufeff" + _RUN_PS1)
    write("run.sh", _RUN_SH)

    write("README.md", _readme(name, slug, framework, spec))

    # 顺手把画布快照存一份，方便脱离数据库回溯
    write("canvas.snapshot.json", json.dumps(graph, ensure_ascii=False, indent=2))

    _clean_caches(project_dir)

    return project_dir, written


def _clean_caches(project_dir: Path) -> None:
    """清掉运行留下的 __pycache__，让目录保持可直接打包的状态。"""
    for cache in project_dir.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    for pyc in project_dir.rglob("*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


_RUN_PS1 = '''<#
  一键运行这个智能体项目。

    .\\run.ps1 "帮我调研一下国产 Agent 框架"
    .\\run.ps1                       # 不带参数会提示输入
    .\\run.ps1 -UseFramework "..."   # 走框架原生入口（需先 -Install）
    .\\run.ps1 -Install              # 只安装 requirements.txt 里的框架依赖

  这个目录是自包含的：runtime_sdk.py / runner.py 都在这里，
  换成任何一台装了 Python 3.9+ 的机器都能直接跑，不依赖 MineAgent 平台。
#>
param(
    [switch]$Install,
    [switch]$UseFramework,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$InputArgs
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$python = 'python'
if (Test-Path (Join-Path $Root '.venv\\Scripts\\python.exe')) {
    $python = Join-Path $Root '.venv\\Scripts\\python.exe'
}

if ($Install) {
    Write-Host '>>> 安装 requirements.txt…' -ForegroundColor Cyan
    & $python -m pip install -r requirements.txt
    if (-not $UseFramework) { exit 0 }
}

$entry = if ($UseFramework) { 'agent.py' } else { 'runner.py' }
$text = if ($InputArgs -and $InputArgs.Count -gt 0) { $InputArgs -join ' ' }
        else { Read-Host '请输入要交给智能体的任务' }
if (-not $text) { Write-Host '没有输入，退出。' -ForegroundColor Yellow; exit 1 }

Write-Host ">>> 用 $entry 开始运行" -ForegroundColor Cyan
& $python $entry --input $text
'''

_RUN_SH = '''#!/usr/bin/env bash
# 一键运行： ./run.sh "你的任务"
#   ./run.sh --install          安装 requirements.txt 里的依赖
#   ./run.sh --framework "..."  走框架原生入口
set -e
cd "$(dirname "$0")"
PY=python3
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"

if [ "$1" = "--install" ]; then
  "$PY" -m pip install -r requirements.txt
  exit 0
fi

ENTRY=runner.py
if [ "$1" = "--framework" ]; then ENTRY=agent.py; shift; fi

TEXT="${1:-}"
[ -z "$TEXT" ] && TEXT="${MINEAGENT_INPUT:-}"
echo ">>> 用 $ENTRY 开始运行"
exec "$PY" "$ENTRY" --input "$TEXT"
'''


def _readme(name: str, slug: str, framework: str, spec: Dict[str, Any]) -> str:
    fw = FRAMEWORK_INDEX.get(framework, {})
    lines = [
        f"# {name}",
        "",
        f"- 画布 slug：`{slug}`",
        f"- 框架：**{fw.get('label', framework)}**（{fw.get('badge', '自定义')}）",
        f"- 节点数：{len(spec['nodes'])}，连线数：{len(spec['edges'])}",
        "",
        "## 这个目录是自包含的",
        "",
        "整个文件夹可以单独拷走、单独部署，不依赖 MineAgent 平台：",
        "`runtime_sdk.py`、`runner.py` 都已经放在目录里，只用 Python 标准库；",
        "只要有 Python 3.9+，换一台机器也能直接跑。",
        "",
        "- 不要把 `nodes/` 或 `runtime_sdk.py` 拆出去单独运行",
        "- 项目目录内不要有 `__pycache__`（.gitignore 已忽略，执行器也不会生成）",
        "",
        "## 运行",
        "",
        "```powershell",
        "# Windows：一键脚本（自动检查依赖、找不到 .venv 就用系统 Python）",
        ".\\run.ps1 \"你的问题\"",
        "",
        "# 或者手动执行",
        "python agent.py --input \"你的问题\"   # 框架原生入口，没装框架会自动回退",
        "python runner.py --input \"你的问题\"  # 内置执行器，零依赖，任何画布都能跑",
        "```",
        "",
        "```bash",
        "# macOS / Linux",
        "./run.sh \"你的问题\"",
        "```",
        "",
        "## 配置模型",
        "",
        "1. 网页「用户中心」或画布设置里填 key（推荐，运行时自动注入）；",
        "2. 或复制 `.env.example` 为 `.env` 并填写 `MINEAGENT_API_KEY`。",
        "",
        "## 目录",
        "",
        "```",
        "agent.json       # 画布图定义（保存时自动覆盖）",
        "agent.py         # 框架原生入口",
        "runner.py        # 内置图执行器（任何画布都能跑）",
        "runtime_sdk.py   # 节点可用的全部能力（ctx.*）",
        "run.ps1          # Windows 一键运行",
        "run.sh           # macOS / Linux 一键运行",
        "nodes/           # 每个节点一个 .py，网页里编辑的就是这里",
        "skills/          # skill.md 技能文件",
        "config.json      # 模型配置（不含 key）",
        "outputs/         # 运行产物",
        ".env.example     # 复制成 .env 填 key，脱离网页独立运行用",
        "```",
        "",
        "## 节点清单",
        "",
        "| 节点 | 类型 | 文件 |",
        "| --- | --- | --- |",
    ]
    for n in spec["nodes"]:
        lines.append(f"| {n['label']} | `{n['kind']}` | `nodes/{n['file']}` |")
    lines.append("")
    return "\n".join(lines)
