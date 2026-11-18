"""画布 → 独立 Agent 项目的代码生成器。"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..config import PROJECTS_DIR
from ..framework_templates import FRAMEWORK_INDEX
from ..node_registry import detect_llm_usage, get_node_type
from ..providers.bindings import strip_secrets
from .graphcheck import check_code
from .dify import render_workflow_dsl
from .native import AGENT_KINDS, TOOL_KINDS, _kind_of, render_agent_full
from .production import (merge_service, render_production_files,
                         render_requirements_extra)

RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"
PROVIDERS_DIR = Path(__file__).resolve().parents[1] / "providers"

REQUIREMENTS = {
    # langchain 1.x：旧的 AgentExecutor / create_react_agent 已移除，改用 create_agent
    "langchain": "langchain>=1.0\nlanggraph>=1.0\nlangchain-openai>=1.0\nlangchain-core>=1.0\n",
    # native.py 生成的 AutoGen 头用的是 0.2 的 `from autogen import ...` 写法，
    # 所以这里要装 pyautogen，而不是 0.4 的 autogen-agentchat
    "autogen": "pyautogen>=0.2.35\n",
    "crewai": "crewai>=0.60.0\n",
    # 节点仍用 langchain 的 @tool / create_agent，编排层换成 smolagents
    "smolagents": ("smolagents>=1.0\nlangchain>=1.0\nlangchain-openai>=1.0\n"
                   "langchain-core>=1.0\n"),
    "agno": ("agno\nlangchain>=1.0\nlangchain-openai>=1.0\n"
             "langchain-core>=1.0\n"),
    "openai_agents": ("openai-agents\nopenai\nlangchain>=1.0\n"
                      "langchain-openai>=1.0\nlangchain-core>=1.0\n"),
    "semantic_kernel": ("semantic-kernel\nopenai\nlangchain>=1.0\n"
                        "langchain-openai>=1.0\nlangchain-core>=1.0\n"),
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
                     model_config: Dict[str, Any],
                     providers: Dict[str, Dict[str, Any]] | None = None) -> Tuple[Path, List[str]]:
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
    for fname in ("runtime_sdk.py", "runner.py", "sandbox.py"):
        shutil.copyfile(RUNTIME_DIR / fname, project_dir / fname)
        written.append(fname)

    # provider 适配层：向量模型 / 向量库 / 数据源。
    # 跟 runtime_sdk 一起走，导出的项目脱离平台也能连自己的库。
    dst_providers = project_dir / "providers"
    if dst_providers.exists():
        shutil.rmtree(dst_providers, ignore_errors=True)
    shutil.copytree(
        PROVIDERS_DIR, dst_providers,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    written.append("providers/")

    # 框架入口：一整个 agent.py，就是这份画布的框架原生代码
    agent_code, node_blocks = render_agent_full(spec, framework)
    # 先按内容算版本：hash 变了才 bump，并把上一版存进 .history/ 供回滚
    version_info = _bump_version(project_dir, spec, agent_code)
    write("agent.py", agent_code)
    write("VERSION", json.dumps(version_info, ensure_ascii=False, indent=2) + "\n")

    # 生成即自检：图结构有硬伤（孤岛 / 无入边 / 工具越权）当场打出来，
    # 不要等用户把项目跑起来才发现。只有真生成了 StateGraph 的代码才有「边」可查。
    has_graph = "build_graph(" in agent_code
    if has_graph:
        issues = check_code(spec, agent_code, node_blocks, TOOL_KINDS, AGENT_KINDS, _kind_of)
        if issues:
            print(f"[codegen:{slug}] 生成自检发现 {len(issues)} 个问题", file=sys.stderr)
            for item in issues:
                print(f"  - {item}", file=sys.stderr)

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
        # 动态扫描这段源码，判断它到底会不会调用大模型；
        # 只看实际写进 agent.py 的那段（用户改过就是用户的），
        # 不要拿 preview_code 兜底，否则用户删掉模型调用也会被模板判回 True
        data["uses_llm"] = detect_llm_usage(block or data.get("code") or "", node["kind"])

    # 模型配置（不含 key）
    cfg = {
        "provider": model_config.get("provider", "deepseek"),
        "base_url": model_config.get("base_url") or "https://api.deepseek.com/v1",
        "model": model_config.get("model") or "deepseek-chat",
        "temperature": model_config.get("temperature", 0.3),
        "max_tokens": model_config.get("max_tokens", 2048),
        "api_key_env": "MINEAGENT_API_KEY",
    }

    # 向量模型 / 向量库 / 数据源：只写配置，密钥靠环境变量注入
    runtime_providers = providers or {}
    provider_env_lines: List[str] = []
    for kind in ("embedding", "vector", "data"):
        block = runtime_providers.get(kind)
        if not block:
            continue
        cfg[kind] = strip_secrets(block)
        env_name = ENV_NAMES.get(kind, f"MINEAGENT_{kind.upper()}_KEY")
        if block.get("api_key") or block.get("password") or block.get("token"):
            provider_env_lines.append(f"{env_name}=")
        cfg[kind + "_env"] = env_name
    if runtime_providers:
        # 节点参数里可以只写个名字，到这里按名字取整份配置
        cfg["embedding_named"] = named_bindings({"embedding": runtime_providers["embedding"]}) \
            if runtime_providers.get("embedding") else {}
        cfg["vector_named"] = named_bindings({"vector": runtime_providers["vector"]}) \
            if runtime_providers.get("vector") else {}
        cfg["data_named"] = named_bindings({"data": runtime_providers["data"]}) \
            if runtime_providers.get("data") else {}

    write("config.json", json.dumps(cfg, ensure_ascii=False, indent=2))

    # Dify 是可视化平台：额外产出一份可直接导入的 workflow DSL + API 触发脚本
    if framework == "dify":
        from .dify import DIFY_CLIENT
        write("dify_workflow.yml", render_workflow_dsl(spec, cfg))
        write("dify_client.py", DIFY_CLIENT)

    session_store = merge_service(graph.get("service"))["session"]["store"]
    requirements_text = (
        REQUIREMENTS.get(framework, "# 无额外依赖（使用内置 runner）\n").rstrip()
        + "\n\n# 服务化依赖（server.py）\n" + render_requirements_extra(session_store)
    )
    write("requirements.txt", requirements_text)

    # 生产化文件：把画布的「服务设置」编译成 server / settings / telemetry / checkpoint
    # 以及 Dockerfile、compose、CI、冒烟测试、依赖锁与离线安装脚本
    prod_files = render_production_files(spec, graph, framework,
                                        requirements_text, has_graph)
    # 换框架 / 改成没有图的画布时，上一轮生成的服务文件要清掉，不然会留一个起不来的镜像
    for stale in ("server.py", "Dockerfile", "docker-compose.yml"):
        if stale not in prod_files:
            (project_dir / stale).unlink(missing_ok=True)
    for rel, content in prod_files.items():
        write(rel, content)

    env_example = (
        "# 复制为 .env 并填入你的 key（网页上配置过的话可以不填）\n"
        "MINEAGENT_API_KEY=sk-xxxx\n"
        f"MINEAGENT_BASE_URL={cfg['base_url']}\n"
        f"MINEAGENT_MODEL={cfg['model']}\n"
        "\n# 模型调用超时 / 客户端重试次数（节点级超时只是兜底，这里才是硬中断）\n"
        "MINEAGENT_LLM_TIMEOUT=120\n"
        "MINEAGENT_LLM_MAX_RETRIES=2\n"
        "\n# 服务鉴权 / 并发（服务设置里配过则不用改）\n"
        "MINEAGENT_AUTH=none\n"
        "MINEAGENT_SERVICE_KEY=\n"
        "MINEAGENT_MAX_CONCURRENCY=4\n"
        "\n# 会话治理：同一个 thread_id 的轮数上限与过期时间（0 表示不限）\n"
        "MINEAGENT_MAX_TURNS=20\n"
        "MINEAGENT_SESSION_TTL=1440\n"
        "\n# 断点续跑：0 时 /resume 返回 501（画布上有审批节点就需要开成 1）\n"
        "MINEAGENT_RESUME=0\n"
        "\n# trace 采样率：0 不落、1 全落、中间按比例（也作用于 OTel span）\n"
        "MINEAGENT_TRACE_SAMPLE=1\n"
        "\n# 可观测：trace 落盘（留空则不落）/ OTel 导出（留空则不导出）\n"
        "MINEAGENT_TRACE_FILE=outputs/traces/{date}.jsonl\n"
        "MINEAGENT_OTEL_ENDPOINT=\n"
        "\n# 成本：每 1K token 单价（填了才会算 cost_usd）；预算耗尽会返回 429\n"
        "MINEAGENT_PRICE_INPUT_PER_1K=0\n"
        "MINEAGENT_PRICE_OUTPUT_PER_1K=0\n"
        "MINEAGENT_BUDGET_USD=0\n"
        "\n# 灰度：0=全走主版本，100=全走 canary；header X-Canary 可强制\n"
        "MINEAGENT_CANARY_PERCENT=0\n"
        "MINEAGENT_CANARY_MODEL=\n"
        "MINEAGENT_CANARY_BASE_URL=\n"
        "MINEAGENT_CANARY_API_KEY=\n"
        "\n# 密钥来源：env（默认）/ file / vault；环境变量仍然优先\n"
        "MINEAGENT_SECRETS=env\n"
        "MINEAGENT_SECRETS_FILE=\n"
        "MINEAGENT_VAULT_ADDR=\n"
        "MINEAGENT_VAULT_TOKEN=\n"
        "MINEAGENT_VAULT_MOUNT=secret\n"
        "MINEAGENT_VAULT_PATH=mineagent\n"
        "\n# 向量模型 / 向量库 / 数据源的访问密钥（在网页「用户中心」配置过则不用填）\n"
        + "".join(line + "\n" for line in provider_env_lines)
        + "\n# 外部数据中台（服务设置 → 数据连接）\n"
        "MINEAGENT_DATA_TOKEN=\n"
        "# 外部评测中台（服务设置 → 评测连接）\n"
        "MINEAGENT_EVAL_TOKEN=\n"
    )
    write(".env.example", env_example)
    write(".gitignore",
          ".env\n.venv/\n.store.db\n*.db\n.sessions.db\n__pycache__/\n*.pyc\n"
          "outputs/*\n!outputs/.gitkeep\nwheels/*\n!wheels/.gitkeep\n"
          ".history/\nevals/candidates.jsonl\n")

    # 空目录留占位文件，保证复制 / 打包 / git 之后目录结构不丢
    write("skills/.gitkeep", "# 技能文件（skill 节点的 skill.md）放这里\n")
    write("outputs/.gitkeep", "# 运行产物会写到这个目录\n")

    # 一键运行脚本：拿到这个文件夹就能跑，不需要记命令
    write("run.ps1", "\ufeff" + _RUN_PS1)
    write("run.sh", _RUN_SH)

    write("README.md", _readme(name, slug, framework, spec))

    # 顺手把画布快照存一份，方便脱离数据库回溯；
    # framework 记进快照，离线检查 / 恢复时不用再问数据库
    snapshot = dict(graph)
    snapshot["framework"] = framework
    snapshot["slug"] = spec.get("slug") or slug
    write("canvas.snapshot.json", json.dumps(snapshot, ensure_ascii=False, indent=2))

    _clean_caches(project_dir)

    return project_dir, written


def _spec_hash(spec: Dict[str, Any]) -> str:
    """按「内容」算版本：节点/连线/代码/参数任何一个变了，hash 就变。"""
    payload = json.dumps(spec, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _bump_version(project_dir: Path, spec: Dict[str, Any], agent_code: str) -> Dict[str, Any]:
    """维护 VERSION：内容没变就不动；变了就 patch +1，并把上一版 agent.py 存进 .history/。

    回滚方式：把 `.history/agent-<旧版本>.py` 拷回 `agent.py` 即可（VERSION 里也记了 hash）。
    """
    version_file = project_dir / "VERSION"
    previous: Dict[str, Any] = {}
    if version_file.exists():
        try:
            previous = json.loads(version_file.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            previous = {}
    if not isinstance(previous, dict):
        previous = {}

    new_hash = _spec_hash(spec)
    if previous.get("hash") == new_hash and previous.get("version"):
        return previous

    version = str(previous.get("version") or "1.0.0")
    if previous:
        parts = version.split(".")
        try:
            parts[-1] = str(int(parts[-1]) + 1)
        except (ValueError, IndexError):
            parts = ["1", "0", "1"]
        version = ".".join(parts[:3]) if len(parts) >= 3 else ".".join(parts + ["0"])

    # 上一版代码留档，出问题能立刻换回去
    previous_agent = project_dir / "agent.py"
    previous_version = str(previous.get("version") or "")
    if previous_agent.exists() and previous_version and previous_version != version:
        history = project_dir / ".history"
        history.mkdir(exist_ok=True)
        try:
            shutil.copyfile(previous_agent, history / f"agent-{previous_version}.py")
            # VERSION 也一起留档：回滚时版本号/hash 才能一并还原
            try:
                from ..versions import archive_version_meta
                archive_version_meta(project_dir, previous_version)
            except Exception:  # noqa: BLE001
                pass
            keep = sorted(history.glob("agent-*.py"), key=lambda p: p.stat().st_mtime)[-5:]
            for stale in history.glob("agent-*.py"):
                if stale not in keep:
                    stale.unlink(missing_ok=True)
        except OSError:
            pass

    info = {
        "version": version,
        "hash": new_hash,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "nodes": len(spec.get("nodes") or []),
        "edges": len(spec.get("edges") or []),
        "bytes": len(agent_code.encode("utf-8")),
    }
    if previous.get("version") != version:
        try:
            changelog = project_dir / "CHANGELOG.md"
            head = "" if changelog.exists() else "# 变更记录\n\n"
            line = (f"- `{info['generated_at']}` **v{version}** · "
                    f"{info['nodes']} 节点 / {info['edges']} 连线 · `{new_hash}`\n")
            with changelog.open("a", encoding="utf-8") as fh:
                fh.write(head + line)
        except OSError:
            pass
    return info


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
        "- 节点代码内联在 `agent.py` 里（不再有 `nodes/` 目录），网页上编辑的就是同一段",
        "- 不要把 `runtime_sdk.py` / `runner.py` 拆出去单独运行",
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
        "agent.json         # 画布图定义（保存时自动覆盖）",
        "agent.py           # 框架原生入口：一张画布 = 一个文件，节点按 ═══ 分块",
        "VERSION            # 版本号 / 内容 hash / 生成时间（/version 直接返回它）",
        "CHANGELOG.md       # 每次内容变化追加一行",
        ".history/          # 最近 5 版 agent.py，回滚就拷这一个文件",
        "runner.py          # 内置图执行器（零依赖，任何画布都能跑）",
        "runtime_sdk.py     # 节点可用的全部能力（ctx.*）",
        "sandbox.py         # shell / exec_python 的隔离实现（MINEAGENT_SANDBOX 控制）",
        "server.py          # FastAPI 服务入口：/chat、/chat/stream、/health、/ready、/metrics",
        "settings.py        # 服务配置（pydantic-settings，启动即校验）",
        "telemetry.py       # JSON 日志 + Prometheus 指标",
        "checkpoint.py      # 会话持久化（SQLite / Postgres）",
        "requirements.txt   # 依赖声明",
        "requirements.lock.txt  # 版本锁（直接依赖全部钉死）",
        "scripts/           # make_lock / offline_bundle / install_offline",
        "wheels/            # 离线包目录（offline_bundle.py 把 wheel 下到这里）",
        "Dockerfile         # 镜像（非 root 运行 + HEALTHCHECK）",
        ".dockerignore      # 保证 .env 不会被打进镜像",
        "docker-compose.yml # 一条命令起服务",
        "integrations/      # 外部数据中台 / 评测中台连接器",
        "evals/             # 评测用例 + 打分脚本（改完 agent 用它证明没变差）",
        "tests/             # pytest 冒烟测试（不需要真实模型）",
        "run.ps1            # Windows 一键运行",
        "run.sh             # macOS / Linux 一键运行",
        "skills/            # skill.md 技能文件",
        "config.json        # 模型配置（不含 key）",
        "outputs/           # 运行产物",
        ".env.example       # 复制成 .env 填 key，脱离网页独立运行用",
        "```",
        "",
        "## 当成服务跑",
        "",
        "```bash",
        "pip install -r requirements.lock.txt",
        "uvicorn server:app --host 0.0.0.0 --port 8000",
        "# 或者",
        "docker compose up --build",
        "```",
        "",
        "返回里的 `usage` 是本次运行的 token 统计；`/metrics` 输出 Prometheus 文本，",
        "`/ready` 会明确列出缺哪项配置。配错配置时进程**直接起不来**，",
        "想看当前生效的配置（key 会打码）：",
        "",
        "```bash",
        "python settings.py",
        "```",
        "",
        "## 离线部署（客户机房没有外网）",
        "",
        "```bash",
        "# ① 在一台能上网、Python 版本与目标机一致的机器上打离线包",
        "python scripts/offline_bundle.py      # 生成 wheels/",
        "",
        "# ② 整个项目目录（含 wheels/）拷到目标机，然后",
        "./scripts/install_offline.sh          # Linux / macOS",
        ".\\scripts\\install_offline.ps1         # Windows",
        "```",
        "",
        "`requirements.lock.txt` 是生成时的版本锁；依赖变动后可以用",
        "`python scripts/make_lock.py` 在装好依赖的环境里重新锁定。",
        "",
        "## 改动后怎么证明没变差",
        "",
        "```bash",
        "python evals/run.py --check   # CI：只校验用例格式与打分逻辑，不调模型",
        "python evals/run.py           # 真跑：需要 key，结果写到 evals/report.json",
        "```",
        "",
        "用例在 `evals/cases.jsonl`，一行一条；`pass_rate` 掉了就是改坏了。",
        "每次请求都会带 `X-Trace-Id`（也可以由调用方传进来），日志和节点事件里都带这个 id，",
        "排查问题时按 trace id 一搜就是完整一条链路。",
        "",
        "## 执行沙箱",
        "",
        "节点里的 `ctx.shell()` / `ctx.exec_python()` 都走 `sandbox.py`，由 `MINEAGENT_SANDBOX` 控制：",
        "",
        "| 取值 | 行为 |",
        "| --- | --- |",
        "| `restricted`（默认） | 限项目目录、清掉密钥环境变量、超时、输出截断 |",
        "| `none` | 不额外限制，只保留超时与输出截断（仅本地开发用） |",
        "| `container` | 在 docker 里跑：无网络、只读根、限内存/CPU/PID；**没装 docker 会直接报错**，不会悄悄退回宿主 |",
        "",
        "节点勾了「工具调用幂等」后，同一次运行里相同参数只会真正执行一次，重跑直接回放结果",
        "（记录在同目录 `.store.db` 的 `tool_calls` 表）。",
        "",
        "## 可观测",
        "",
        "```bash",
        "curl -s localhost:8000/metrics | head        # Prometheus 文本（/metrics/json 是 JSON）",
        "curl -s localhost:8000/runs/<thread_id>      # 会话停在哪、有没有待审批",
        "```",
        "",
        "- 每次请求都带 `X-Trace-Id`；日志里的 `trace_id` 可用来串整条链路",
        "- trace 落盘：`MINEAGENT_TRACE_FILE=outputs/traces/{date}.jsonl`（按天切）",
        "- 接 OTel：`MINEAGENT_OTEL_ENDPOINT=http://collector:4318/v1/traces`，",
        "  需要 `pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http`；",
        "  没装会在启动日志里明确告警，不会静默不导出",
        "- 装了 OTel 后每个节点也会是一个子 span（带 `node.id` / `node.kind`），",
        "  在 Jaeger/Tempo 里能直接看到「请求 → 哪几个节点各花多久」",
        "- 看板：`docs/grafana-dashboard.json` 可直接 import 到 Grafana，导入时选一下 Prometheus 数据源",
        "- 采样：`MINEAGENT_TRACE_SAMPLE` 控制 trace 落盘与 OTel span 的采样率（0 不落 / 1 全落）",
        "- 会话治理：`MINEAGENT_MAX_TURNS` 到顶、`MINEAGENT_SESSION_TTL` 过期时会清掉该 thread 的检查点并从头开始，",
        "  `/metrics` 的 `session_reset_total` 记了次数；一次性请求（不传 thread_id）不受影响",
        "- 成本：填 `MINEAGENT_PRICE_INPUT_PER_1K` / `_OUTPUT_PER_1K` 后，响应里的 `usage.cost_usd` 就是本次花费，",
        "  `/metrics` 会累加 `mineagent_cost_usd_total`；设 `MINEAGENT_BUDGET_USD` 后超预算直接 429",
        "",
        "## 密钥放哪",
        "",
        "默认还是环境变量（跟以前一样）；现场想用受控文件或 Vault 时改 `MINEAGENT_SECRETS`，代码不用动：",
        "",
        "| 取值 | 需要配 | 说明 |",
        "| --- | --- | --- |",
        "| `env`（默认） | — | 只读环境变量 |",
        "| `file` | `MINEAGENT_SECRETS_FILE=/etc/mineagent/secrets.json` | JSON 键值，建议 `chmod 600` |",
        "| `vault` | `MINEAGENT_VAULT_ADDR` / `_TOKEN` / `_MOUNT` / `_PATH` | Vault KV v2 |",
        "",
        "查找顺序默认「环境变量 → provider」，设 `MINEAGENT_SECRETS_PRIORITY=provider` 可反过来。",
        "provider 连不上只告警一次并退回环境变量，服务照常起；`/ready.secrets` 会显示当前来源与是否配齐。",
        "",
        "## 改完之后的版本与回滚",
        "",
        "每次保存画布，生成器都会按内容算一个 hash：",
        "",
        "- 内容没变 → `VERSION` 不动",
        "- 内容变了 → patch +1，`CHANGELOG.md` 追加一行，上一版 `agent.py` 存进 `.history/`（保留最近 5 版）",
        "",
        "```bash",
        "curl -s localhost:8000/version     # {\"version\":\"1.0.3\",\"hash\":\"…\",\"generated_at\":\"…\"}",
        "curl -s localhost:8000/health      # {\"ok\":true,\"version\":\"1.0.3\"}",
        "",
        "# 回滚到上一版：把留档文件拷回去，重启即可",
        "cp .history/agent-1.0.2.py agent.py",
        "```",
        "",
        "## 评测飞轮：把线上失败变成用例",
        "",
        "`/chat` 出错时会自动把这条请求写进 `evals/candidates.jsonl`（含 input / error / trace_id）。",
        "",
        "```bash",
        "python evals/run.py --candidates   # 重跑这些失败输入，看现在还报不报错",
        "```",
        "",
        "不再报错的输入，抄进 `cases.jsonl` 再补上 `expect_contains`，就成了一条正式用例——",
        "修过的 bug 从此有了回归测试。",
        "",
        "## 灰度发布",
        "",
        "配一套 canary 模型，让一小部分流量先走新版本：",
        "",
        "```bash",
        "MINEAGENT_CANARY_BASE_URL=https://新模型地址/v1 \\",
        "MINEAGENT_CANARY_MODEL=新模型名 \\",
        "MINEAGENT_CANARY_PERCENT=10 \\",
        "uvicorn server:app --host 0.0.0.0 --port 8000",
        "```",
        "",
        "- 分流按 `trace_id` 做稳定哈希，同一个请求不会在两条链路间摇摆；",
        "- 也可以用 header 强制：`X-Canary: 1` 走 canary、`X-Canary: 0` 走主版本（做对比验证很方便）；",
        "- 响应体有 `variant` 字段、响应头有 `X-Variant`，日志与 trace 里也带；",
        "- `/metrics` 里 `mineagent_chat_canary_total` 与 `mineagent_chat_primary_total` 可直接对比成功率与延迟。",
        "",
        "## 安全：护栏 / 脱敏 / 审计",
        "",
        "三项都由服务设置（`settings.py`）驱动，`/ready.security` 能看到当前值：",
        "",
        "| 开关 | 取值 | 行为 |",
        "| --- | --- | --- |",
        "| `MINEAGENT_GUARDRAIL` | `off` / `log` / `block` | 输入过长或像提示词注入时：只记录 / 直接 400 |",
        "| `MINEAGENT_MAX_INPUT_CHARS` | 默认 8000，0 为不限 | 输入长度上限 |",
        "| `MINEAGENT_PII` | `1` / `0` | 输出、日志、trace、评测候选里的手机号/身份证/邮箱/卡号替换成 `[phone]` 这类占位符 |",
        "| `MINEAGENT_AUDIT` | `1` / `0` | 把每次 chat / resume / 被拦截写入 `outputs/audit/<日期>.jsonl` |",
        "",
        "审计只记「谁（token 指纹 + IP + UA）在什么时候做了什么、结果如何」，**不记用户正文和原始 token**。",
        "",
        "```bash",
        "MINEAGENT_GUARDRAIL=block MINEAGENT_PII=1 MINEAGENT_AUDIT=1 uvicorn server:app",
        "curl -s localhost:8000/ready | jq .security",
        "```",
        "",
        "## 压测与验收",
        "",
        "```bash",
        "python scripts/loadtest.py --url http://127.0.0.1:8000/chat \\",
        "    --requests 200 --concurrency 8 --slo-p95-ms 30000",
        "python scripts/loadtest.py --url http://127.0.0.1:8000/chat/stream \\",
        "    --stream --requests 50 --slo-p95-ms 8000",
        "```",
        "",
        "脚本输出 JSON 摘要，末行是「SLO 判定：达标/不达标」，退出码可直接进流水线。",
        "完整验收清单在 `docs/acceptance.md`（服务能起、冒烟、SLO、可观测、安全、交付物）。",
        "",
        "## 人工审批（挂起 / 放行）",
        "",
        "画布上的 `human_approval` 节点会真的把整条 run 挂起，等外部放行后再继续：",
        "",
        "> 开关：`MINEAGENT_RESUME=1` 才允许 `/resume`（默认 0 返回 501）。画布上有审批节点就把这个打开。",
        "",
        "```bash",
        "# ① 发起：可能直接返回结果，也可能返回待审批",
        "curl -X POST localhost:8000/chat -H 'Content-Type: application/json' \\",
        "     -d '{\"message\":\"草稿\",\"thread_id\":\"t1\"}'",
        "# → {\"status\":\"interrupted\",\"interrupt\":{\"question\":\"…\"},\"thread_id\":\"t1\"}",
        "",
        "# ② 看看停在哪",
        "curl localhost:8000/runs/t1",
        "",
        "# ③ 放行（decision 也可以是 reject）",
        "curl -X POST localhost:8000/resume -H 'Content-Type: application/json' \\",
        "     -d '{\"thread_id\":\"t1\",\"decision\":\"approve\"}'",
        "```",
        "",
        "挂起状态靠 checkpointer 保存：`MINEAGENT_SESSION_STORE=sqlite`（默认）重启也能续跑，",
        "`none` 只在进程内有效，`postgres` 适合多副本部署。",
        "",
        "## 节点清单",
        "",
        "| 节点 | 类型 |",
        "| --- | --- |",
    ]
    for n in spec["nodes"]:
        lines.append(f"| {n['label']} | `{n['kind']}` |")
    lines.append("")
    return "\n".join(lines)
