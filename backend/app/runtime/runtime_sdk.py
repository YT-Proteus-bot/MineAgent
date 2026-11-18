# Copyright 2026 YT-Proteus-bot
# SPDX-License-Identifier: Apache-2.0
# Part of MineAgent: https://github.com/YT-Proteus-bot/MineAgent

"""MineAgent 项目运行时 SDK。

这段代码会被复制到每一个画布项目目录（projects/<画布>/runtime_sdk.py），
画布上的每个节点就是 `nodes/*.py` 里的一个 `run(ctx)` 函数。

它零第三方依赖，只用标准库，所以只要本机有 Python 就能跑；
装了对应框架（langgraph / autogen / crewai）时，agent.py 会走框架原生实现，
否则 runner.py 用内置解释器执行同一批节点函数。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

EVENT_PREFIX = "@@EVENT@@"
EVENT_STREAM = sys.stdout

PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_DIR / "config.json"

# 执行类能力统一交给 sandbox.py；老项目里没有这个文件时退回本文件内的实现
try:  # pragma: no cover - 取决于项目目录里是否有 sandbox.py
    import sandbox as _sandbox
except Exception:  # noqa: BLE001
    _sandbox = None


# --------------------------------------------------------------------------- #
# 事件输出
# --------------------------------------------------------------------------- #
class _SafeStream:
    """保证事件不因为编码问题炸掉。"""

    def write(self, s: str) -> int:  # pragma: no cover
        try:
            return EVENT_STREAM.write(s)
        except UnicodeEncodeError:
            return EVENT_STREAM.write(s.encode("utf-8", "replace").decode("utf-8"))
        return 0

    def flush(self) -> None:  # pragma: no cover
        EVENT_STREAM.flush()


_out = _SafeStream()


def emit_event(event: Dict[str, Any]) -> None:
    _out.write(EVENT_PREFIX + json.dumps(event, ensure_ascii=False, default=str) + "\n")
    _out.flush()


def dotenv() -> Dict[str, str]:
    """读项目根目录的 .env。每次调用都重新读，改完不用重启进程。"""
    out: Dict[str, str] = {}
    env_file = PROJECT_DIR / ".env"
    if not env_file.exists():
        return out
    try:
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return out


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def _providers_layer():
    """惰性拿到 providers 适配层。

    生成的项目里 providers/ 与 runtime_sdk.py 同级；在平台内则挂在 app 包下。
    拿不到时返回 None，调用方回退到内置的本地实现。
    """
    try:
        import providers as layer  # 项目内
        return layer
    except ImportError:
        pass
    try:
        from app import providers as layer  # 平台内
        return layer
    except ImportError:
        return None


def _apply_secret_env(cfg: Dict[str, Any], env_name: str) -> Dict[str, Any]:
    """把 api_key_env 指向的密钥从环境变量 / .env 里补进配置。"""
    if not env_name:
        return cfg
    value = os.environ.get(env_name) or _file_env().get(env_name, "")
    if value:
        cfg = dict(cfg)
        cfg["api_key"] = value
    return cfg


_FILE_ENV: Optional[Dict[str, str]] = None


def _file_env() -> Dict[str, str]:
    """读项目内的 .env（导出后独立运行时用）。"""
    global _FILE_ENV
    if _FILE_ENV is not None:
        return _FILE_ENV
    data: Dict[str, str] = {}
    env_file = PROJECT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    _FILE_ENV = data
    return data


def load_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    # 项目内 .env（导出后独立运行用）
    file_env: Dict[str, str] = _file_env()
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    cfg["api_key"] = (
        os.environ.get("MINEAGENT_API_KEY")
        or file_env.get("MINEAGENT_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or file_env.get("OPENAI_API_KEY")
        or ""
    )
    cfg["base_url"] = os.environ.get("MINEAGENT_BASE_URL") or cfg.get("base_url") or cfg["base_url"]
    cfg["model"] = os.environ.get("MINEAGENT_MODEL") or cfg.get("model") or cfg["model"]
    return cfg


# --------------------------------------------------------------------------- #
# HTTP / LLM
# --------------------------------------------------------------------------- #
def _normalize_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        base = "https://api.openai.com/v1"
    if base.endswith("/chat/completions"):
        return base
    if not base.endswith("/v1") and "/v1" not in base:
        base += "/v1"
    return base + "/chat/completions"


class JudgeUnavailable(RuntimeError):
    """没有配置 Jev，或者认证不通过；节点可以据此回退到普通模型判断。"""


def _open(req: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout)


def http_json(method: str, url: str, headers: Optional[Dict[str, str]] = None,
              payload: Any = None, timeout: float = 60.0) -> Any:
    data = None
    hdrs = {"User-Agent": "MineAgent/1.0", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
    with _open(req, timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw}


def chat_completion(messages: List[Dict[str, str]], cfg: Optional[Dict[str, Any]] = None,
                    model: Optional[str] = None, temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None, timeout: float = 180.0) -> str:
    cfg = cfg or load_config()
    if not cfg.get("api_key"):
        raise RuntimeError(
            "缺少模型 API Key：请在网页右上角「用户中心」或画布设置里配置，"
            "或在项目目录创建 .env 写入 MINEAGENT_API_KEY=sk-xxx"
        )
    payload = {
        "model": model or cfg.get("model"),
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3) if temperature is None else temperature,
        "max_tokens": max_tokens or cfg.get("max_tokens", 2048),
        "stream": False,
    }
    resp = http_json("POST", _normalize_url(cfg.get("base_url", "")),
                     headers={"Authorization": f"Bearer {cfg['api_key']}"},
                     payload=payload, timeout=timeout)
    try:
        return resp["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"模型返回格式异常：{str(resp)[:400]}")


def chat_stream(messages: List[Dict[str, str]], cfg: Optional[Dict[str, Any]] = None,
                model: Optional[str] = None, on_token: Optional[Callable[[str], None]] = None,
                timeout: float = 300.0) -> str:
    cfg = cfg or load_config()
    if not cfg.get("api_key"):
        raise RuntimeError("缺少模型 API Key，请先在用户中心或画布设置里配置")
    payload = {
        "model": model or cfg.get("model"),
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": cfg.get("max_tokens", 2048),
        "stream": True,
    }
    req = urllib.request.Request(
        _normalize_url(cfg.get("base_url", "")),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg['api_key']}",
                 "Accept": "text/event-stream"},
        method="POST",
    )
    chunks: List[str] = []
    with _open(req, timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
                delta = obj["choices"][0]["delta"].get("content") or ""
            except Exception:
                continue
            if delta:
                chunks.append(delta)
                if on_token:
                    on_token(delta)
    return "".join(chunks)


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    for pattern in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pattern, text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                continue
    return None


# --------------------------------------------------------------------------- #
# 轻量向量（无外部依赖，离线可用）
# --------------------------------------------------------------------------- #
def local_embed(text: str, dim: int = 256) -> List[float]:
    vec = [0.0] * dim
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower())
    for tok in tokens:
        for gram in (tok, tok[:3], tok[-3:]):
            h = 0
            for ch in gram:
                h = (h * 131 + ord(ch)) & 0xFFFFFFFF
            vec[h % dim] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a, b = list(a), list(b)
    return sum(x * y for x, y in zip(a, b))


def _wiki_slug(text: str) -> str:
    """把标题变成安全的文件名：保留中英文数字，其余压成连字符。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", (text or "").strip().lower())
    s = s.strip("-")[:48]
    return s or "page"


# --------------------------------------------------------------------------- #
# 节点上下文
# --------------------------------------------------------------------------- #
@dataclass
class ToolSpec:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "传入工具的参数"}},
        "required": ["query"],
    })

    def schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": re.sub(r"[^\w]", "_", self.name)[:64],
                "description": self.description[:512],
                "parameters": self.parameters,
            },
        }

    def __call__(self, **kwargs):
        return self.func(**kwargs)


class NodeContext:
    """节点函数拿到的全部能力都在这里。"""

    def __init__(self, node_id: str, node_name: str, kind: str, params: Dict[str, Any],
                 payload: Any, state: Dict[str, Any], run_id: str = "",
                 org: Optional[Dict[str, Any]] = None,
                 model_override: Optional[Dict[str, Any]] = None,
                 delegate_fn: Optional[Callable[[str, Any], Any]] = None,
                 embedding_config: Optional[Dict[str, Any]] = None,
                 vector_config: Optional[Dict[str, Any]] = None,
                 data_config: Optional[Dict[str, Any]] = None):
        self.node_id = node_id
        self.node_name = node_name
        self.kind = kind
        self.params = params or {}
        self.input = payload
        self.state = state
        self.run_id = run_id
        self.tools: List[ToolSpec] = []
        self.config = load_config()
        self.org = org or {}
        self._model_override = model_override or {}
        self._delegate_fn = delegate_fn
        self.cfg = self._effective_config()
        # 向量模型 / 向量库 / 数据源：节点参数 > 传入的配置 > config.json
        self.embedding_config = self._provider_cfg(
            "embedding", embedding_config, self.params.get("embedding"))
        self.vector_config = self._provider_cfg(
            "vector", vector_config, self.params.get("vector_store") or self.params.get("vector"))
        self.data_config = self._provider_cfg("data", data_config, self.params.get("data"))
        self._store_cache: Optional[Any] = None

    def _provider_cfg(self, section: str, explicit: Optional[Dict[str, Any]],
                      from_params: Optional[Any]) -> Dict[str, Any]:
        """选出一个实例的配置。

        config.json 里的结构是 {"default": 名字, "items": {名字: 配置}}；
        老项目是单个 dict，这里兼容掉。优先级：
            节点参数里写的实例名 > 显式传入 > 画布默认 > 第一条。
        """
        block = self.config.get(section)
        items: Dict[str, Any] = {}
        default_name = ""
        if isinstance(block, dict) and isinstance(block.get("items"), dict):
            items = block["items"]
            default_name = str(block.get("default") or "")
        elif isinstance(block, dict) and block:
            items = {"default": block}
            default_name = "default"

        wanted = ""
        if isinstance(from_params, str) and from_params.strip():
            wanted = from_params.strip()
        elif isinstance(from_params, dict):
            wanted = str(from_params.get("_name") or "")

        chosen: Dict[str, Any] = {}
        if wanted and isinstance(items.get(wanted), dict):
            chosen = dict(items[wanted])
        elif default_name and isinstance(items.get(default_name), dict):
            chosen = dict(items[default_name])
        elif items:
            first = next(iter(items.values()))
            if isinstance(first, dict):
                chosen = dict(first)

        if isinstance(explicit, dict):
            chosen.update({k: v for k, v in explicit.items() if k != "_name"})
        if isinstance(from_params, dict):
            chosen.update({k: v for k, v in from_params.items() if k != "_name"})
        if not chosen:
            return {}
        env_name = chosen.get("api_key_env") or ""
        return _apply_secret_env(chosen, str(env_name))

    def _effective_config(self) -> Dict[str, Any]:
        """节点级模型配置优先于项目 config.json。"""
        if not self._model_override:
            return self.config
        cfg = dict(self.config)
        for key in ("provider", "base_url", "model", "temperature", "max_tokens"):
            val = self._model_override.get(key)
            if val not in (None, ""):
                cfg[key] = val
        env_name = self._model_override.get("api_key_env")
        if env_name:
            key = os.environ.get(env_name)
            if key:
                cfg["api_key"] = key
        return cfg

    # ---- 组织关系（上下级 / 平级） ----
    @property
    def superior(self) -> str:
        """我的上级 agent 名字（没配就是空串）。"""
        return str(self.org.get("superior_name") or "")

    @property
    def subordinates(self) -> List[str]:
        """我的下级 agent 名字列表。"""
        return list(self.org.get("subordinate_names") or [])

    @property
    def peers(self) -> List[str]:
        """和我平级的 agent 名字列表。"""
        return list(self.org.get("peer_names") or [])

    def delegate(self, name: str, task: Any) -> Any:
        """把任务交给某个下级（或平级）agent 执行，返回它的输出。"""
        if self._delegate_fn is None:
            raise RuntimeError("当前运行环境不支持委派（runner 未注入 delegate）")
        emit_event({"event": "delegate", "node": self.node_id, "from": self.node_name,
                    "to": name, "task": str(task)[:600]})
        return self._delegate_fn(name, task)

    def delegate_many(self, tasks: List[Tuple[str, Any]], max_workers: int = 4,
                      timeout: float = 180.0) -> List[Dict[str, Any]]:
        """并行派给多个 agent（Super-agent 的 Worker 层）。

        多个 worker 各自独立跑，互不阻塞；任何一个失败不会拖垮其它，
        结果里会标明成功还是失败。
        """
        if self._delegate_fn is None:
            raise RuntimeError("当前运行环境不支持委派（runner 未注入 delegate）")
        if not tasks:
            return []

        def run_one(idx: int, name: str, task: Any) -> Dict[str, Any]:
            started = time.time()
            emit_event({"event": "delegate_start", "node": self.node_id, "worker": name,
                        "index": idx, "task": str(task)[:300]})
            try:
                out = self._delegate_fn(name, task)
                return {"worker": name, "ok": True, "output": out,
                        "duration_ms": int((time.time() - started) * 1000)}
            except Exception as exc:  # noqa: BLE001
                return {"worker": name, "ok": False, "error": str(exc)[:500],
                        "duration_ms": int((time.time() - started) * 1000)}

        results: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            futures = [pool.submit(run_one, i, n, t) for i, (n, t) in enumerate(tasks)]
            for fut in as_completed(futures, timeout=timeout):
                try:
                    results.append(fut.result())
                except Exception as exc:  # noqa: BLE001
                    results.append({"worker": "?", "ok": False, "error": str(exc)[:500]})
        emit_event({"event": "delegate_done", "node": self.node_id,
                    "total": len(results), "failed": sum(1 for r in results if not r["ok"])})
        return results

    # ---- 输入 ----
    @property
    def text(self) -> str:
        if self.input is None:
            return ""
        if isinstance(self.input, str):
            return self.input
        if isinstance(self.input, (dict, list)):
            for key in ("text", "answer", "output", "content", "result", "formatted"):
                if isinstance(self.input, dict) and isinstance(self.input.get(key), str):
                    return self.input[key]
            return json.dumps(self.input, ensure_ascii=False, indent=2)
        return str(self.input)

    # ---- 日志与事件 ----
    def log(self, message: str, level: str = "info") -> None:
        emit_event({"event": "log", "level": level, "node": self.node_id,
                    "name": self.node_name, "message": str(message)[:4000]})

    def emit(self, kind: str, payload: Any) -> None:
        emit_event({"event": "custom", "type": kind, "node": self.node_id,
                    "name": self.node_name, "payload": payload})

    def route(self, branch: str) -> None:
        self.state["__branch__"] = branch

    # ---- 模型 ----
    def llm(self, prompt: str, system: Optional[str] = None, model: Optional[str] = None,
            temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        messages: List[Dict[str, str]] = []
        sys_prompt = system or self.state.get("system_prompt")
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": str(prompt)})
        result = chat_completion(messages, self.cfg, model=model, temperature=temperature,
                                 max_tokens=max_tokens)
        # 粗略估算 token 用量，供 budget_guard / cost_tracker 使用
        self.state["tokens_used"] = int(self.state.get("tokens_used", 0)) + (
            len(str(prompt)) + len(result)) // 4
        return result

    def llm_stream(self, prompt: str, system: Optional[str] = None, model: Optional[str] = None) -> str:
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": str(prompt)})
        return chat_stream(messages, self.cfg, model=model,
                           on_token=lambda t: emit_event({"event": "token", "node": self.node_id,
                                                          "name": self.node_name, "text": t}))

    def json_prompt(self, instruction: str, schema: Any, context: Any = "") -> Any:
        prompt = (
            f"{instruction}\n\n## 待处理内容\n{context if context != '' else self.text}\n\n"
            f"## 输出格式（严格 JSON，不要额外解释）\n{json.dumps(schema, ensure_ascii=False)}"
        )
        raw = self.llm(prompt, system="你只输出符合要求结构的 JSON。")
        data = _extract_json(raw)
        return schema if data is None else data

    # ---- Agent 推理模式 ----
    def agent(self, task: str, tools: Optional[List[ToolSpec]] = None,
              system: Optional[str] = None, mode: str = "react",
              max_steps: int = 6) -> str:
        """按推理模式跑一个 agent。

        mode:
          react        思考-行动-观察循环（默认）
          plan_execute 先规划，再逐步执行，最后汇总
          goal         围绕目标反复推进，自评达成度直到达标
          reflexion    先出稿，再自我批判并重写
          tool_call    只做一轮工具调用
          simple       单次推理，不循环、不用工具
        """
        tools = tools if tools is not None else self.tools
        mode = (mode or "react").strip().lower()
        base_system = system or "你是一个能自主使用工具的智能体。"
        emit_event({"event": "agent_mode", "node": self.node_id,
                    "name": self.node_name, "mode": mode})

        if mode == "simple":
            return self._remember_answer(self.llm(task, system=base_system))
        if mode == "tool_call":
            return self._remember_answer(self._agent_tool_call(task, tools, base_system))
        if mode == "plan_execute":
            return self._remember_answer(self._agent_plan_execute(task, tools, base_system, max_steps))
        if mode == "goal":
            return self._remember_answer(self._agent_goal(task, tools, base_system, max_steps))
        if mode == "reflexion":
            return self._remember_answer(self._agent_reflexion(task, tools, base_system, max_steps))
        return self._remember_answer(self._agent_react(task, tools, base_system, max_steps))

    def _remember_answer(self, answer: str) -> str:
        """把 agent 的回答留在 state 里，output 节点可以优先取它。"""
        self.state["answer"] = answer
        return answer

    def _tool_desc(self, tools: List[ToolSpec]) -> str:
        return "\n".join(f"- {t.name}: {t.description}" for t in tools) or "（无可用工具）"

    def _call_tool(self, tools: List[ToolSpec], action: Any, args: Any, step: int,
                   transcript: List[str]) -> str:
        tool = next((t for t in tools if re.sub(r"[^\w]", "_", t.name) ==
                     re.sub(r"[^\w]", "_", str(action))), None)
        if tool is None:
            transcript.append(f"第{step}步：调用未知工具 {action}，跳过")
            return ""
        if not isinstance(args, dict):
            args = {"query": str(args)}
        try:
            result = tool(**args)
        except Exception as exc:  # noqa: BLE001
            result = f"工具执行失败：{exc}"
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        transcript.append(f"第{step}步：{tool.name}({json.dumps(args, ensure_ascii=False)}) -> {text[:600]}")
        emit_event({"event": "tool_call", "node": self.node_id, "tool": tool.name,
                    "args": args, "result": text[:2000]})
        self.state.setdefault("observations", []).append(
            {"node": self.node_name, "summary": text[:400], "raw": text})
        return text

    def _agent_react(self, task: str, tools: List[ToolSpec], base_system: str,
                     max_steps: int) -> str:
        tool_desc = self._tool_desc(tools)
        transcript: List[str] = []
        scratch = task
        for step in range(1, max_steps + 1):
            emit_event({"event": "agent_step", "node": self.node_id, "step": step,
                        "max_steps": max_steps, "mode": "react"})
            prompt = (
                f"{scratch}\n\n## 可用工具\n{tool_desc}\n\n"
                f"## 已执行步骤\n{chr(10).join(transcript) or '（暂无）'}\n\n"
                "请决定下一步。只输出一个 JSON：\n"
                '{"thought": "...", "action": "工具名", "action_input": {"query": "..."}}\n'
                '如果已经可以给出最终答案，输出：{"thought": "...", "final_answer": "..."}'
            )
            raw = self.llm(prompt, system=base_system)
            decision = _extract_json(raw) or {}
            if not isinstance(decision, dict):
                return raw
            if decision.get("final_answer"):
                return str(decision["final_answer"])
            text = self._call_tool(tools, decision.get("action"),
                                   decision.get("action_input") or {}, step, transcript)
            if not text:
                continue
            scratch = f"{task}\n\n（上一轮工具结果：{text[:800]}）"
        return self.llm(
            f"{task}\n\n## 执行记录\n{chr(10).join(transcript)}\n\n请给出最终答案。",
            system=base_system,
        )

    def _agent_tool_call(self, task: str, tools: List[ToolSpec], base_system: str) -> str:
        if not tools:
            return self.llm(task, system=base_system)
        prompt = (
            f"{task}\n\n## 可用工具\n{self._tool_desc(tools)}\n\n"
            "只决定一次工具调用，输出 JSON：\n"
            '{"action": "工具名", "action_input": {"query": "..."}}\n'
            '如果不需要工具，输出：{"action": "", "final_answer": "..."}'
        )
        raw = self.llm(prompt, system=base_system)
        decision = _extract_json(raw) or {}
        if not isinstance(decision, dict):
            return raw
        if decision.get("final_answer"):
            return str(decision["final_answer"])
        transcript: List[str] = []
        text = self._call_tool(tools, decision.get("action"),
                               decision.get("action_input") or {}, 1, transcript)
        if not text:
            return raw
        return self.llm(
            f"{task}\n\n工具返回：{text[:1500]}\n\n请据此给出最终答案。",
            system=base_system)

    def _agent_plan_execute(self, task: str, tools: List[ToolSpec], base_system: str,
                            max_steps: int) -> str:
        plan = self.llm(
            f"任务：{task}\n\n请拆成 2-5 个执行步骤，每行一步，只输出步骤本身。",
            system="你是任务规划专家，只输出步骤清单，不要额外解释。")
        emit_event({"event": "agent_step", "node": self.node_id, "step": 0,
                    "max_steps": max_steps, "mode": "plan_execute", "plan": plan[:1500]})
        steps = [s.strip(" -•·\t") for s in plan.splitlines() if s.strip()][:5]
        if not steps:
            return self._agent_react(task, tools, base_system, max_steps)
        results: List[str] = []
        for idx, step_desc in enumerate(steps, 1):
            if idx > max_steps:
                break
            emit_event({"event": "agent_step", "node": self.node_id, "step": idx,
                        "max_steps": max_steps, "mode": "plan_execute",
                        "subtask": step_desc[:200]})
            out = self._agent_react(
                f"总任务：{task}\n当前步骤（{idx}/{len(steps)}）：{step_desc}\n"
                f"已完成部分：{chr(10).join(results) or '（暂无）'}",
                tools, base_system, max(2, min(3, max_steps)))
            results.append(f"步骤{idx}（{step_desc}）：{out}")
        return self.llm(
            f"总任务：{task}\n\n## 各步骤结果\n{chr(10).join(results)}\n\n请汇总输出最终答案。",
            system=base_system)

    def _agent_goal(self, task: str, tools: List[ToolSpec], base_system: str,
                    max_steps: int) -> str:
        history: List[str] = []
        last = ""
        for round_no in range(1, max_steps + 1):
            emit_event({"event": "agent_step", "node": self.node_id, "step": round_no,
                        "max_steps": max_steps, "mode": "goal"})
            last = self._agent_react(
                f"目标：{task}\n\n## 已完成的尝试\n{chr(10).join(history) or '（暂无）'}\n\n"
                "请继续推进；如果已经能完整达成目标，直接给出最终答案。",
                tools, base_system, max(2, max_steps // 2 or 2))
            check = self.json_prompt(
                "判断当前答案是否已经达成目标，并指出还差什么。",
                schema={"achieved": False, "score": 0, "missing": ["..."]},
                context=f"目标：{task}\n\n当前答案：\n{last}")
            if not isinstance(check, dict):
                break
            try:
                score = int(check.get("score") or 0)
            except (TypeError, ValueError):
                score = 0
            self.emit("goal_check", {"round": round_no, "score": score,
                                     "achieved": bool(check.get("achieved")),
                                     "missing": check.get("missing")})
            if check.get("achieved") or score >= 85:
                break
            history.append(f"第{round_no}轮（{score} 分，未达成）：{last[:400]}")
        return last

    def _agent_reflexion(self, task: str, tools: List[ToolSpec], base_system: str,
                         max_steps: int) -> str:
        draft = self._agent_react(task, tools, base_system, max(2, max_steps // 2 or 2))
        rounds = max(1, min(3, max(1, max_steps // 2)))
        for i in range(rounds):
            emit_event({"event": "agent_step", "node": self.node_id, "step": i + 1,
                        "max_steps": rounds, "mode": "reflexion"})
            critique = self.llm(
                f"任务：{task}\n\n当前产出：\n{draft}\n\n"
                "请指出事实错误、遗漏与表达问题，越具体越好。",
                system="你是严格的评审者，只输出问题清单。")
            draft = self.llm(
                f"任务：{task}\n\n上一版产出：\n{draft}\n\n评审意见：\n{critique}\n\n"
                "请据此重写，只输出改进后的完整结果。",
                system=base_system)
        return draft

    # ---- 外部能力 ----
    def http(self, method: str, url: str, headers: Optional[Dict[str, str]] = None,
             params: Optional[Dict[str, Any]] = None, json: Any = None,
             data: Any = None, timeout: float = 60.0) -> Any:
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return http_json(method, url, headers=headers, payload=json if json is not None else data,
                         timeout=timeout)

    def fetch_text(self, url: str, limit: int = 8000) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 MineAgent/1.0"})
        with _open(req, 30) as resp:
            html = resp.read().decode("utf-8", "replace")
        html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    def search(self, query: str, limit: int = 5) -> str:
        """联网搜索。

        优先用 ddgs（它处理了 DuckDuckGo 对脚本请求的反爬，返回结构化结果）；
        没装 ddgs 时退回直接抓 HTML —— 后者经常被反爬拦成空页，所以会带上提示。
        """
        try:
            from ddgs import DDGS  # type: ignore

            rows = DDGS().text(query, max_results=max(1, int(limit))) or []
            lines: List[str] = []
            for idx, row in enumerate(rows[:max(1, int(limit))], 1):
                title = str(row.get("title") or "").strip()
                body = str(row.get("body") or "").strip()
                href = str(row.get("href") or "").strip()
                line = f"{idx}. {title}"
                if body:
                    line += "\n   " + body
                if href:
                    line += "\n   " + href
                lines.append(line)
            if lines:
                return "\n".join(lines)
            return "（ddgs 没有返回结果，换个关键词试试）"
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            if "No results" in str(exc):
                return "（没有搜到结果，换个关键词试试）"
            self.log(f"ddgs 搜索失败，改用直接抓取：{exc}", "warn")

        try:
            url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
            page = self.fetch_text(url, limit=20000)
            if "result__a" not in page:
                return "（直接抓取被反爬拦了。装 ddgs 可稳定联网搜索：pip install ddgs）"
            return page[:4000]
        except Exception as exc:  # noqa: BLE001
            self.log(f"联网搜索失败：{exc}", "warn")
            return ""

    def skill(self, name: str = "", inline: str = "") -> str:
        if inline and inline.strip():
            return inline.strip()
        if name:
            for base in (PROJECT_DIR / "skills", PROJECT_DIR, PROJECT_DIR / "skills_import"):
                p = base / name
                if p.exists() and p.is_file():
                    return p.read_text(encoding="utf-8", errors="replace")
        return "（未找到技能文件，请填写 skill.md 内容或文件名）"

    # ---- 记忆 ----
    def remember(self, key: str, value: Any, long_term: bool = False) -> None:
        self.state.setdefault("memory", {})[key] = value
        if long_term:
            store = _open_store()
            store.execute(
                "CREATE TABLE IF NOT EXISTS memory(key TEXT, value TEXT, ts REAL)",
                (),
            )
            store.execute("INSERT INTO memory VALUES(?,?,?)",
                          (key, json.dumps(value, ensure_ascii=False, default=str), time.time()))
            store.commit()

    def recall(self, key: str, default: Any = None) -> Any:
        if key in self.state.get("memory", {}):
            return self.state["memory"][key]
        try:
            store = _open_store()
            store.execute("CREATE TABLE IF NOT EXISTS memory(key TEXT, value TEXT, ts REAL)", ())
            rows = store.execute(
                "SELECT value FROM memory WHERE key=? ORDER BY ts DESC LIMIT 1", (key,)
            ).fetchall()
            store.commit()
            if rows:
                return json.loads(rows[0][0])
        except Exception:
            pass
        return default

    def history(self, key: str = "conversation") -> List[Any]:
        val = self.recall(key, [])
        if isinstance(val, list):
            return val
        return [val] if val else []

    # ---- 结构化判断（Jev / TypeSafe System One）----
    def judge(self, state: Any, questions: Dict[str, Any],
              model: Optional[str] = None, timeout: float = 20.0) -> Dict[str, Any]:
        """把「state + 类型化问题」交给 Jev，拿回带概率的答案。

        不生成文本、不做解释，只回答选择题 / 判断题 / 打分题，
        适合意图路由、安全检查、优先级判定这类"模糊 if"。

        questions 写法：
            {"intent": {"type": "choice", "instructions": "这句话属于哪个意图？",
                        "criteria": {"咨询": None, "执行": None, "闲聊": None}},
             "urgent": {"type": "noul", "instructions": "是否要求立刻处理？"},
             "effort": {"type": "score", "instructions": "处理复杂度",
                        "criteria": ["一句话", "几分钟", "要查资料"]}}

        返回：{"answers": {"intent": {"choice": "咨询", "confidence": 0.93,
                                      "probabilities": {...}}, ...},
               "model": "jev-1.13.0", "usage": {...}}
        """
        endpoint = (
            os.environ.get("JEV_ENDPOINT")
            or dotenv().get("JEV_ENDPOINT")
            or "https://api.typesafe.ai/v1/systemone"
        )
        key = (
            os.environ.get("TYPESAFE_API_KEY")
            or os.environ.get("JEV_API_KEY")
            or dotenv().get("TYPESAFE_API_KEY")
            or dotenv().get("JEV_API_KEY")
        )
        if not key:
            raise JudgeUnavailable(
                "没有配置 Jev 的 API Key。设置环境变量 TYPESAFE_API_KEY，"
                "或在项目 .env 里写 TYPESAFE_API_KEY=sk-... 后再试"
            )
        if not questions:
            raise ValueError("judge() 至少需要一个 question")

        body: Dict[str, Any] = {"state": state, "questions": questions}
        if model:
            body["model"] = model
        elif os.environ.get("JEV_MODEL") or dotenv().get("JEV_MODEL"):
            body["model"] = os.environ.get("JEV_MODEL") or dotenv().get("JEV_MODEL")

        try:
            resp = http_json(
                "POST", endpoint,
                headers={"Authorization": f"Bearer {key}"},
                payload=body, timeout=timeout,
            )
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            # 这几类属于"Jev 这次用不了"，节点可以安静地回退到普通模型
            if exc.code in (401, 403, 404, 451):
                raise JudgeUnavailable(
                    f"Jev 不可用（{exc.code}）：{detail or '认证失败或所在地区不可用'}"
                ) from exc
            if exc.code == 429:
                raise JudgeUnavailable("Jev 限流（429），这次先回退") from exc
            # 422 这类是请求本身写错了，不该悄悄回退，要暴露出来
            raise RuntimeError(f"Jev 返回 {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise JudgeUnavailable(f"连不上 Jev（{endpoint}）：{exc.reason}") from exc

        if not isinstance(resp, dict) or "answers" not in resp:
            raise RuntimeError(f"Jev 返回格式异常：{str(resp)[:200]}")
        return resp

    # ---- LLM Wiki：入库时就理解，而不是查询时才拼 ----
    def wiki_ingest(self, text: str, title: str = "", source: str = "",
                    links: Optional[List[str]] = None) -> Dict[str, Any]:
        """把一段内容整理成一个 wiki 页面落到 wiki/ 目录。

        和传统 RAG 的区别：切块入库之后还会让模型读懂、提炼摘要和要点、
        建议互链，写成一页可读的 markdown。查询时直接读页，而不是从碎片里拼。
        """
        wiki_dir = PROJECT_DIR / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        body = (text or "").strip()
        if not body:
            raise ValueError("wiki_ingest 需要内容")

        data: Dict[str, Any] = {}
        try:
            data = self.json_prompt(
                "把这段资料整理成一页 wiki：给标题、三到五条要点、一两句摘要，"
                "并指出它可能和哪些主题相关（主题名用简短名词）。",
                schema={"title": "", "summary": "", "points": [], "links": []},
                context=f"原始标题：{title or '（无）'}\n内容：\n{body[:6000]}",
            ) or {}
        except Exception:  # noqa: BLE001
            data = {}

        page_title = title or str(data.get("title") or "").strip() or body[:24]
        slug = _wiki_slug(page_title)
        points = data.get("points") or []
        related = links or data.get("links") or []
        summary = str(data.get("summary") or "").strip()

        lines = [
            "---",
            f"title: {page_title}",
            f"slug: {slug}",
            f"source: {source or 'inline'}",
            f"updated: {time.strftime('%Y-%m-%dT%H:%M:%S')}",
            f"links: [{', '.join(str(x) for x in related)}]",
            "---",
            "",
            f"# {page_title}",
            "",
        ]
        if summary:
            lines += ["## 摘要", "", summary, ""]
        if points:
            lines += ["## 要点", ""] + [f"- {p}" for p in points] + [""]
        lines += ["## 原文", "", body[:8000], ""]
        if related:
            lines += ["## 相关", ""] + [f"- [[{x}]]" for x in related] + [""]

        path = wiki_dir / f"{slug}.md"
        path.write_text("\n".join(lines), encoding="utf-8")

        index = self.wiki_index()
        index[slug] = {
            "title": page_title,
            "summary": summary,
            "links": [str(x) for x in related],
            "source": source or "inline",
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        (wiki_dir / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

        self.emit("wiki_ingest", {"slug": slug, "title": page_title})
        return {"slug": slug, "title": page_title, "path": f"wiki/{slug}.md",
                "points": len(points), "links": related}

    def wiki_index(self) -> Dict[str, Any]:
        """读 wiki/index.json（没有就返回空表）。"""
        path = PROJECT_DIR / "wiki" / "index.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def wiki_pages(self) -> List[Dict[str, Any]]:
        """列出所有 wiki 页面（按更新时间倒序）。"""
        idx = self.wiki_index()
        items = [{"slug": k, **v} for k, v in idx.items() if isinstance(v, dict)]
        items.sort(key=lambda x: str(x.get("updated", "")), reverse=True)
        return items

    def wiki_read(self, slug: str) -> str:
        """读一整页 wiki 的 markdown。"""
        path = PROJECT_DIR / "wiki" / f"{_wiki_slug(slug)}.md"
        if not path.exists():
            raise FileNotFoundError(f"没有这个 wiki 页面：{slug}")
        return path.read_text(encoding="utf-8", errors="replace")

    def wiki_query(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """在 wiki 里找最相关的页面。

        先用标题/摘要/要点的字面重合粗排（便宜），命中不明确时再让模型
        从候选里挑——比向量检索更能利用"入库时已经理解过的结构"。
        """
        pages = self.wiki_pages()
        if not pages:
            return []
        q_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", (query or "").lower()))

        scored: List[Dict[str, Any]] = []
        for p in pages:
            hay = f"{p.get('title','')} {p.get('summary','')} {' '.join(map(str, p.get('links') or []))}"
            hay_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", hay.lower()))
            overlap = len(q_tokens & hay_tokens) / (len(q_tokens) or 1)
            scored.append({**p, "score": round(overlap, 4)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[: max(top_k * 2, 4)]

        # 粗排没有明显命中的，交给模型从候选里挑
        if not top or top[0]["score"] == 0:
            try:
                picked = self.json_prompt(
                    "下面是知识库里的页面，挑出和问题最相关的几个（只返回 slug）。",
                    schema={"slugs": []},
                    context="问题：" + (query or "") + "\n页面：" + json.dumps(
                        [{"slug": p["slug"], "title": p.get("title", "")} for p in scored[:12]],
                        ensure_ascii=False),
                ) or {}
                want = set(picked.get("slugs") or [])
                top = [p for p in scored if p["slug"] in want] or top
            except Exception:  # noqa: BLE001
                pass

        out: List[Dict[str, Any]] = []
        for p in top[:top_k]:
            try:
                content = self.wiki_read(p["slug"])
            except Exception:  # noqa: BLE001
                content = ""
            out.append({**p, "content": content[:4000]})
        return out

    # ---- 向量 ----
    @property
    def has_embedding(self) -> bool:
        """是否配了真实向量模型（否则用内置哈希向量兜底）。"""
        return bool(self.embedding_config.get("model"))

    def embed(self, text: str) -> List[float]:
        """把一条文本转成向量。

        配了真实向量模型就走它；没配才回退到内置的 256 维哈希向量。
        配了但调用失败会抛错，不静默降级——否则索引和查询可能落在不同空间。
        """
        return self.embed_many([text])[0] if text or text == "" else []

    def embed_many(self, texts: List[str], input_type: str = "document") -> List[List[float]]:
        items = [t if isinstance(t, str) else str(t) for t in (texts or [])]
        if not items:
            return []
        if not self.has_embedding:
            if not self.state.get("__embed_warned__"):
                self.state["__embed_warned__"] = True
                self.log("没有配置向量模型，使用内置哈希向量（结果只适合演示）", "warn")
            return [local_embed(t) for t in items]
        layer = _providers_layer()
        if layer is None:
            raise RuntimeError("providers 适配层缺失，无法调用向量模型")
        return layer.embed_texts(self.embedding_config, items, input_type=input_type)

    def _vector_store(self):
        """按配置造一个向量库适配器；没配就返回 None（走内置 SQLite 老路径）。"""
        if self._store_cache is not None:
            return self._store_cache or None
        if not self.vector_config:
            self._store_cache = False
            return None
        layer = _providers_layer()
        if layer is None:
            raise RuntimeError("providers 适配层缺失，无法连接向量库")
        cfg = dict(self.vector_config)
        cfg.setdefault("base_dir", str(PROJECT_DIR))
        self._store_cache = layer.get_store(cfg)
        return self._store_cache

    @property
    def vector_collection(self) -> str:
        return str(self.vector_config.get("collection") or "default")

    def use_collection(self, name: str) -> None:
        """临时切到另一个集合（节点参数里指定集合名时用）。"""
        if not name:
            return
        self.vector_config = {**self.vector_config, "collection": str(name)}
        self._store_cache = None

    def _ensure_store_collection(self, dim: int) -> None:
        store = self._vector_store()
        if store is None:
            return
        store.ensure_collection(
            self.vector_collection, dim,
            self.vector_config.get("metric", "cosine"),
            self.embedding_config.get("model", ""))

    def retrieve(self, query: str, top_k: int = 4, folders: Optional[List[str]] = None,
                 mode: str = "hybrid") -> List[Dict[str, Any]]:
        """从项目内的 skills/ docs/ outputs/ 召回片段。

        mode: hybrid（向量+关键词加权） / vector / keyword
        """
        folders = folders or ["skills", "docs", "outputs"]
        mode = (mode or "hybrid").lower()
        qv = local_embed(query)
        q_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", (query or "").lower()))
        scored: List[Dict[str, Any]] = []
        for folder in folders:
            base = PROJECT_DIR / folder
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".db", ".pyc"}:
                    continue
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for i, chunk in enumerate(_chunk(content, 600)):
                    vscore = cosine(qv, local_embed(chunk))
                    if mode == "vector":
                        score = vscore
                    else:
                        toks = set(re.findall(r"[\w\u4e00-\u9fff]+", chunk.lower()))
                        kscore = len(q_tokens & toks) / (len(q_tokens) or 1)
                        score = kscore if mode == "keyword" else 0.65 * vscore + 0.35 * kscore
                    scored.append({
                        "source": str(path.relative_to(PROJECT_DIR)).replace("\\", "/"),
                        "chunk": chunk,
                        "score": round(float(score), 4),
                        "index": i,
                    })
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def rerank(self, query: str, docs: List[Any], top_k: int = 3) -> List[Dict[str, Any]]:
        """让模型给候选片段打相关性分并重排；模型不可用时回退到向量相似度。"""
        items: List[Dict[str, Any]] = []
        for i, doc in enumerate(docs or []):
            if isinstance(doc, str):
                text = doc
            elif isinstance(doc, dict):
                text = str(doc.get("chunk") or doc.get("text") or doc.get("content") or doc)
            else:
                text = str(doc)
            items.append({"id": i, "text": text})
        if not items:
            return []
        trimmed = items[:12]
        prompt = (
            f"问题：{query}\n\n"
            + "\n".join(f"[{it['id']}] {it['text'][:600]}" for it in trimmed)
            + "\n\n给每个片段与问题的相关性打 0-1 分。"
        )
        data = self.json_prompt(
            prompt, schema={"scores": [{"id": 0, "score": 0.0}]}, context="")
        scores: Dict[int, float] = {}
        if isinstance(data, dict) and isinstance(data.get("scores"), list):
            for row in data["scores"]:
                try:
                    scores[int(row.get("id"))] = float(row.get("score"))
                except (TypeError, ValueError):
                    continue
        if not scores:
            qv = local_embed(query)
            for it in trimmed:
                scores[it["id"]] = cosine(qv, local_embed(it["text"]))
        ranked = [{**it, "score": round(scores.get(it["id"], 0.0), 4)} for it in trimmed]
        ranked.sort(key=lambda x: x["score"], reverse=True)
        self.emit("rerank", {"in": len(items), "out": min(top_k, len(ranked))})
        return ranked[:top_k]

    def build_context(self, docs: List[Any], max_chars: int = 3000) -> str:
        """把检索结果拼成带编号的参考上下文。"""
        lines: List[str] = []
        used = 0
        for i, doc in enumerate(docs or [], 1):
            if isinstance(doc, dict):
                text = str(doc.get("chunk") or doc.get("text") or doc.get("content") or "")
                src = doc.get("source") or doc.get("path") or ""
            else:
                text, src = str(doc), ""
            text = text.strip()
            if not text:
                continue
            block = f"[{i}] {text}" + (f"\\n（来源：{src}）" if src else "")
            if used + len(block) > max_chars:
                remain = max_chars - used
                if remain > 80:
                    lines.append(block[:remain] + "…")
                break
            lines.append(block)
            used += len(block)
        return "\n\n".join(lines)

    def split_text(self, text: str, chunk_size: int = 600, overlap: int = 80) -> List[str]:
        """按段落切块，超长段落再按句子切，块间保留重叠。"""
        text = (text or "").strip()
        if not text:
            return []
        size = max(80, int(chunk_size))
        ov = max(0, min(int(overlap), size // 2))
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            paragraphs = [text]
        chunks: List[str] = []
        buf = ""
        for para in paragraphs:
            while len(para) > size:
                if buf:
                    chunks.append(buf)
                    buf = ""
                cut = para[:size]
                chunks.append(cut)
                para = para[size - ov:]
            if len(buf) + len(para) + 2 <= size:
                buf = f"{buf}\n\n{para}" if buf else para
            else:
                if buf:
                    chunks.append(buf)
                buf = para
        if buf:
            chunks.append(buf)
        return chunks

    def load_document(self, path: str) -> str:
        """读取 pdf / docx / md / txt / csv / json 的纯文本。"""
        target = self._resolve_project_path(path)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在：{path}")
        suffix = target.suffix.lower()
        if suffix in {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".py", ".html", ".htm"}:
            return target.read_text(encoding="utf-8", errors="replace")
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader  # type: ignore
            except Exception:
                return ("[缺少依赖] 解析 PDF 需要 pypdf：请执行 pip install pypdf，"
                        "或先把 PDF 转成 txt 放到 docs/ 下")
            reader = PdfReader(str(target))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        if suffix == ".docx":
            try:
                import docx  # type: ignore
            except Exception:
                return ("[缺少依赖] 解析 docx 需要 python-docx：请执行 pip install python-docx")
            doc = docx.Document(str(target))
            return "\n".join(p.text for p in doc.paragraphs)
        return target.read_text(encoding="utf-8", errors="replace")

    def _resolve_project_path(self, path: str) -> Path:
        p = Path(path)
        target = (p if p.is_absolute() else PROJECT_DIR / p).resolve()
        if PROJECT_DIR not in target.parents and target != PROJECT_DIR:
            raise PermissionError("只能访问项目目录内的文件")
        return target

    def parse_table(self, text: str) -> List[Dict[str, Any]]:
        """把 CSV 或 Markdown 表格解析成行字典。"""
        rows: List[Dict[str, Any]] = []
        lines = [ln for ln in (text or "").splitlines() if ln.strip()]
        if not lines:
            return rows
        if "|" in lines[0]:
            def cells(line: str) -> List[str]:
                return [c.strip() for c in line.strip().strip("|").split("|")]
            header = cells(lines[0])
            for line in lines[1:]:
                if set(line.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                    continue
                vals = cells(line)
                rows.append({header[i]: (vals[i] if i < len(vals) else "") for i in range(len(header))})
            return rows
        header = [c.strip() for c in re.split(r"[,\t]", lines[0])]
        for line in lines[1:]:
            vals = [c.strip() for c in re.split(r"[,\t]", line)]
            rows.append({header[i]: (vals[i] if i < len(vals) else "") for i in range(len(header))})
        return rows

    def ocr_text(self, path: str) -> str:
        target = self._resolve_project_path(path)
        if not target.exists():
            raise FileNotFoundError(f"图片不存在：{path}")
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
            return pytesseract.image_to_string(Image.open(str(target)), lang="chi_sim+eng")
        except Exception as exc:  # noqa: BLE001
            return (f"[缺少依赖] OCR 需要 pytesseract + Pillow（{exc}）。"
                    "也可以先把图片里的文字手工贴进 skill 节点")

    def describe_image(self, path: str) -> str:
        target = self._resolve_project_path(path)
        if not target.exists():
            raise FileNotFoundError(f"图片不存在：{path}")
        return (f"[需要多模态模型] 当前后端只接了文本模型，无法直接理解图片 {target.name}。"
                "可以在节点参数里把图片描述手动写进 prompt，或换成支持视觉的模型后再扩展这里。")

    def transcribe(self, path: str) -> str:
        target = self._resolve_project_path(path)
        if not target.exists():
            raise FileNotFoundError(f"音频不存在：{path}")
        try:
            from faster_whisper import WhisperModel  # type: ignore
            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(str(target))
            return "".join(seg.text for seg in segments)
        except Exception as exc:  # noqa: BLE001
            return (f"[缺少依赖] 语音转写需要 faster-whisper（{exc}），"
                    "安装后再重试：pip install faster-whisper")

    def parse_json(self, text: str) -> Any:
        """从任意文本里抽出 JSON。"""
        return _extract_json(text)

    # ---- 键值 / 缓存 / 图 ----
    def kv_set(self, key: str, value: Any) -> None:
        store = _open_store()
        store.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT, ts REAL)", ())
        store.execute(
            "INSERT INTO kv(key,value,ts) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
            (str(key), json.dumps(value, ensure_ascii=False, default=str), time.time()),
        )
        store.commit()

    def kv_get(self, key: str, default: Any = None) -> Any:
        store = _open_store()
        store.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT, ts REAL)", ())
        row = store.execute("SELECT value FROM kv WHERE key=?", (str(key),)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]

    def cache_key(self, text: str) -> str:
        import hashlib
        raw = f"{self.node_name}:{text}"
        return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:24]

    def cache_get(self, key: str) -> Any:
        store = _open_store()
        store.execute(
            "CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, value TEXT, exp REAL)", ())
        row = store.execute("SELECT value, exp FROM cache WHERE key=?", (str(key),)).fetchone()
        if not row:
            return None
        if row[1] and row[1] < time.time():
            store.execute("DELETE FROM cache WHERE key=?", (str(key),))
            store.commit()
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]

    def cache_set(self, key: str, value: Any, ttl: int = 3600) -> None:
        store = _open_store()
        store.execute(
            "CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, value TEXT, exp REAL)", ())
        exp = time.time() + ttl if ttl else 0
        store.execute(
            "INSERT INTO cache(key,value,exp) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, exp=excluded.exp",
            (str(key), json.dumps(value, ensure_ascii=False, default=str), exp),
        )
        store.commit()

    def graph_query(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """在项目内的 triples 表里按关键词找关系（subject, predicate, object）。"""
        store = _open_store()
        store.execute(
            "CREATE TABLE IF NOT EXISTS triples(subject TEXT, predicate TEXT, object TEXT)", ())
        like = f"%{query}%"
        rows = store.execute(
            "SELECT subject, predicate, object FROM triples "
            "WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ? LIMIT ?",
            (like, like, like, int(limit)),
        ).fetchall()
        if not rows:
            return [{"hint": "triples 表还是空的，请先用 db_write 或自定义节点写入关系"}]
        return [{"subject": r[0], "predicate": r[1], "object": r[2]} for r in rows]

    def exec_sql(self, sql: str, readonly: bool = True) -> Any:
        """执行 SQL。readonly=True 时只允许 SELECT。"""
        store = _open_store()
        try:
            if readonly and not re.match(r"^\s*(select|with)\b", sql, re.I):
                raise PermissionError("只读模式下只允许 SELECT / WITH")
            cur = store.execute(sql)
            if cur.description:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()][:500]
            store.commit()
            return {"rowcount": cur.rowcount}
        finally:
            pass

    def wait_for_slot(self, per_minute: int = 30) -> None:
        """朴素限流：一分钟内最多 per_minute 次。"""
        now = time.time()
        window = [t for t in (self.state.get("__rate__") or []) if now - t < 60]
        if len(window) >= max(1, per_minute):
            wait = 60 - (now - window[0])
            if wait > 0:
                self.log(f"触发限流，等待 {wait:.1f}s", "warn")
                time.sleep(min(wait, 30))
            window = []
        window.append(now)
        self.state["__rate__"] = window[-per_minute:]

    def vector_upsert(self, text: str, metadata: Optional[Dict[str, Any]] = None,
                      doc_id: str = "") -> Dict[str, Any]:
        """写入一条向量。配了外部向量库就写它，否则写内置 SQLite 表。"""
        vec = self.embed(text)
        store = self._vector_store()
        if store is None:
            # 内置兜底：保持老表结构不变，老项目不受影响
            db = _open_store()
            db.execute("CREATE TABLE IF NOT EXISTS vectors(id TEXT, text TEXT, vec TEXT)", ())
            vid = doc_id or f"{self.node_id}-{int(time.time() * 1000)}"
            db.execute("INSERT INTO vectors VALUES(?,?,?)",
                       (vid, text, json.dumps(vec)))
            db.commit()
            return {"id": vid, "stored": True, "backend": "sqlite"}

        self._ensure_store_collection(len(vec))
        vid = doc_id or f"{self.node_id}-{int(time.time() * 1000)}"
        store.upsert(self.vector_collection, [{
            "id": vid, "text": text, "vector": vec, "metadata": metadata or {},
        }])
        return {"id": vid, "stored": True, "backend": store.protocol,
                "collection": self.vector_collection}

    def vector_search(self, query: str, top_k: int = 4,
                      where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """按相似度取回最相关的若干条。"""
        store = self._vector_store()
        if store is None:
            db = _open_store()
            db.execute("CREATE TABLE IF NOT EXISTS vectors(id TEXT, text TEXT, vec TEXT)", ())
            qvec = self.embed(query)
            out = []
            for vid, text, vec in db.execute("SELECT id, text, vec FROM vectors").fetchall():
                out.append({"id": vid, "text": text,
                            "score": round(cosine(qvec, json.loads(vec)), 4)})
            out.sort(key=lambda x: x["score"], reverse=True)
            return out[:top_k]

        qvec = self.embed_many([query], input_type="query")[0]
        return store.search(self.vector_collection, qvec, top_k=top_k, where=where)

    def vector_delete(self, ids: List[str]) -> int:
        store = self._vector_store()
        if store is None:
            return 0
        return store.delete(self.vector_collection, ids)

    def vector_store_drop(self, name: str = "") -> bool:
        """清空整个集合（换 embedding 模型后必须重建索引时用）。"""
        store = self._vector_store()
        if store is None:
            return False
        store.drop(name or self.vector_collection)
        return True

    # ---- 数据源（业务库 / 文档库 / 图库 / 缓存） ----
    def _data_db(self):
        if not self.data_config:
            return None
        layer = _providers_layer()
        if layer is None:
            raise RuntimeError("providers 适配层缺失，无法连接数据源")
        cfg = dict(self.data_config)
        cfg.setdefault("base_dir", str(PROJECT_DIR))
        return layer.get_database(cfg)

    def query_data(self, statement: str, limit: int = 100,
                   params: Optional[Any] = None) -> List[Dict[str, Any]]:
        """读数据源。SQL / Cypher / Redis 命令 / Mongo filter JSON 都走这里。"""
        db = self._data_db()
        if db is None:
            return self.query_sql(statement)
        return db.query(statement, params=params, limit=limit)

    def write_data(self, statement: str, params: Optional[Any] = None) -> int:
        """写数据源（DDL / INSERT / UPDATE / Cypher 写 / Redis 写命令）。"""
        db = self._data_db()
        if db is None:
            raise RuntimeError("还没有配置数据源，无法执行写操作")
        return db.write(statement, params=params)

    def data_tables(self) -> List[str]:
        db = self._data_db()
        return db.collections() if db is not None else []

    # ---- 执行类（统一走 sandbox.py，只有一处需要审）----
    def exec_python(self, code: str, timeout: float = 30.0) -> Dict[str, str]:
        if _sandbox is not None:
            return _sandbox.run_python(code, timeout=timeout)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snippet.py"
            path.write_text(code, encoding="utf-8")
            try:
                proc = subprocess.run([sys.executable, str(path)], capture_output=True,
                                      text=True, timeout=timeout, cwd=str(PROJECT_DIR),
                                      encoding="utf-8", errors="replace")
                return {"stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}
            except subprocess.TimeoutExpired:
                return {"stdout": "", "stderr": f"执行超时（{timeout}s）"}

    def shell(self, command: str, timeout: float = 60.0) -> Dict[str, str]:
        if _sandbox is not None:
            return _sandbox.run_shell(command, timeout=timeout)
        proc = subprocess.run(command, shell=True, capture_output=True, text=True,
                              timeout=timeout, cwd=str(PROJECT_DIR),
                              encoding="utf-8", errors="replace")
        return {"code": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}

    def read_file(self, rel_path: str) -> str:
        p = (PROJECT_DIR / rel_path).resolve()
        if PROJECT_DIR not in p.parents and p != PROJECT_DIR:
            raise PermissionError("只能访问项目目录内的文件")
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

    def write_file(self, rel_path: str, content: str) -> str:
        p = (PROJECT_DIR / rel_path).resolve()
        if PROJECT_DIR not in p.parents and p != PROJECT_DIR:
            raise PermissionError("只能写入项目目录内的文件")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if isinstance(content, str) else str(content), encoding="utf-8")
        return str(p.relative_to(PROJECT_DIR)).replace("\\", "/")

    def query_sql(self, sql: str) -> List[Dict[str, Any]]:
        if not re.match(r"^\s*(select|with)\b", sql, re.I):
            raise PermissionError("只允许只读查询（SELECT / WITH）")
        store = _open_store()
        try:
            cur = store.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, row)) for row in cur.fetchall()][:500]
        finally:
            store.close()

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, min(float(seconds), 30.0)))

    def validate(self, data: Any, schema: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        if not isinstance(schema, dict) or not schema:
            return errors
        for key, expected in schema.items():
            if isinstance(data, dict):
                if key not in data:
                    errors.append(f"缺少字段 {key}")
                elif isinstance(expected, list) and not isinstance(data[key], list):
                    errors.append(f"字段 {key} 应为数组")
                elif isinstance(expected, dict) and not isinstance(data[key], dict):
                    errors.append(f"字段 {key} 应为对象")
        return errors

    def ask_human(self, question: str, default: str = "approve") -> str:
        self.emit("human_approval", {"question": question[:2000], "auto": default})
        self.log(f"需要人工审批（无交互环境，按默认值 {default} 处理）", "warn")
        return default

    def run_subgraph(self, project: str, payload: Any) -> Any:
        target = (PROJECT_DIR.parent / project).resolve()
        if not (target / "runner.py").exists():
            raise FileNotFoundError(f"找不到子图项目：{project}")
        proc = subprocess.run(
            [sys.executable, str(target / "runner.py"), "--input",
             payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, timeout=600, cwd=str(target),
            encoding="utf-8", errors="replace",
        )
        for line in (proc.stdout or "").splitlines():
            if line.startswith(EVENT_PREFIX):
                try:
                    evt = json.loads(line[len(EVENT_PREFIX):])
                except Exception:
                    continue
                if evt.get("event") == "run_end":
                    return evt.get("output", "")
        return proc.stdout[-2000:]

    # ---- 框架桥接（装了对应依赖就走原生实现，没装则降级为通用实现） ----
    def _framework_ready(self, module: str) -> bool:
        try:
            __import__(module)
            return True
        except Exception:
            return False

    def autogen_assistant(self, name: str, system_message: str, task: str) -> str:
        try:
            from autogen_agentchat.agents import AssistantAgent  # type: ignore
            from autogen_ext.models.openai import OpenAIChatCompletionClient  # type: ignore
            import asyncio

            client = OpenAIChatCompletionClient(
                model=self.cfg["model"], base_url=self.cfg.get("base_url"),
                api_key=self.cfg["api_key"],
                model_info={"vision": False, "function_calling": True, "json_output": True,
                            "family": "unknown", "structured_output": False},
            )

            async def _run():
                agent = AssistantAgent(name=name, model_client=client,
                                       system_message=system_message)
                res = await agent.run(task=task)
                await client.close()
                return getattr(res, "messages", [])[-1].content if getattr(res, "messages", []) else ""

            return asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.log(f"AutoGen 原生调用不可用（{exc}），降级为通用 LLM 调用", "warn")
            return self.llm(task, system=system_message)

    def autogen_user_proxy(self, name: str, task: str, human_input_mode: str = "NEVER") -> str:
        self.log(f"UserProxy({name}) 转交任务，human_input_mode={human_input_mode}")
        return task

    def autogen_group_chat(self, agents: List[str], task: str, max_round: int = 6) -> str:
        try:
            from autogen_agentchat.agents import AssistantAgent  # type: ignore
            from autogen_agentchat.teams import RoundRobinGroupChat  # type: ignore
            from autogen_ext.models.openai import OpenAIChatCompletionClient  # type: ignore
            import asyncio

            client = OpenAIChatCompletionClient(
                model=self.cfg["model"], base_url=self.cfg.get("base_url"),
                api_key=self.cfg["api_key"],
                model_info={"vision": False, "function_calling": True, "json_output": True,
                            "family": "unknown", "structured_output": False},
            )

            async def _run():
                members = [AssistantAgent(name=a, model_client=client,
                                          system_message=f"你是 {a}，负责该角色的工作。") for a in agents]
                team = RoundRobinGroupChat(members, max_turns=max_round)
                res = await team.run(task=task)
                await client.close()
                return getattr(res, "messages", [])[-1].content if getattr(res, "messages", []) else ""

            return asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.log(f"AutoGen GroupChat 不可用（{exc}），降级为多角色轮询", "warn")
            transcript = []
            for a in agents:
                transcript.append(f"{a}: {self.llm(task, system=f'你是 {a}，从你的角色出发给出意见。')}")
            return self.llm(f"讨论：{transcript}\n\n综合输出结论。", system="你是主持人。")

    def crewai_agent(self, role: str, goal: str, backstory: str, task: str) -> str:
        self.state.setdefault("crewai_agents", []).append(
            {"role": role, "goal": goal, "backstory": backstory})
        return self.llm(task or goal, system=f"你是{role}。目标：{goal}。背景：{backstory}")

    def crewai_task(self, description: str, expected_output: str, agent: str = "") -> str:
        self.state.setdefault("crewai_tasks", []).append(
            {"description": description, "expected_output": expected_output, "agent": agent})
        return self.llm(
            f"任务：{description}\n期望产出：{expected_output}\n输入：{self.text}",
            system=f"你是{agent or '执行者'}，只输出任务产出。")

    def crewai_crew(self, agents: List[Any], tasks: List[Any], process: str, task: str) -> str:
        ctx_agents = agents or self.state.get("crewai_agents", [])
        ctx_tasks = tasks or self.state.get("crewai_tasks", [])
        transcript = []
        for t in ctx_tasks:
            desc = t.get("description") if isinstance(t, dict) else str(t)
            transcript.append(self.llm(f"{desc}\n原始输入：{task}", system="你是 Crew 中的执行者。"))
        return self.llm(
            f"团队产出：{transcript}\n请汇总为最终交付物。", system="你是 Crew Manager。")

    def crewai_tool(self, name: str, description: str, payload: Any) -> Any:
        return {"tool": name, "description": description, "payload": payload,
                "result": f"（{name} 工具占位实现，请在节点代码里替换为真实逻辑）"}

    def mcp_call(self, server: str, tool: str, args: Dict[str, Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": tool, "arguments": args}}
        return http_json("POST", server, headers={"Content-Type": "application/json"},
                         payload=payload, timeout=120)


# --------------------------------------------------------------------------- #
# 项目级快捷函数：给生成的原生 agent.py 用
# --------------------------------------------------------------------------- #
_SHARED_CTX: Optional["NodeContext"] = None


def _shared_context() -> "NodeContext":
    """读 config.json 里的 embedding / vector / data 三段，造一个共享上下文。

    原生 agent.py 里的节点是 `def xxx(state) -> dict`，没有 ctx。
    这些函数让它们复用同一套 provider 适配层，
    保证「内置 runner 预览」和「原生代码」行为一致。
    """
    global _SHARED_CTX
    if _SHARED_CTX is None:
        cfg = load_config()
        _SHARED_CTX = NodeContext(
            node_id="__shared__", node_name="__shared__", kind="shared",
            params={}, payload="", state={},
            embedding_config=cfg.get("embedding"),
            vector_config=cfg.get("vector"),
            data_config=cfg.get("data"),
        )
    return _SHARED_CTX


def project_embed(text: str, input_type: str = "document") -> List[float]:
    """把文本转成向量（读项目 config.json 的向量模型配置）。"""
    ctx = _shared_context()
    return ctx.embed_many([text], input_type=input_type)[0]


def project_vector_upsert(text: str, metadata: Optional[Dict[str, Any]] = None,
                          doc_id: str = "") -> Dict[str, Any]:
    return _shared_context().vector_upsert(text, metadata=metadata, doc_id=doc_id)


def project_vector_search(query: str, top_k: int = 4,
                          where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return _shared_context().vector_search(query, top_k=top_k, where=where)


def project_vector_collection() -> str:
    return _shared_context().vector_collection


def project_use_collection(name: str) -> None:
    """切到另一个集合（节点参数里指定集合名时用）。"""
    _shared_context().use_collection(name)


def project_retrieve(query: str, top_k: int = 4, mode: str = "hybrid",
                     folders: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """从项目内文件（skills/ docs/ outputs/）召回片段。"""
    return _shared_context().retrieve(query, top_k=top_k, mode=mode,
                                      folders=folders)


def project_query_data(statement: str, limit: int = 100) -> List[Dict[str, Any]]:
    return _shared_context().query_data(statement, limit=limit)


def _chunk(text: str, size: int) -> List[str]:
    text = text.strip()
    if not text:
        return []
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf = [], ""
    for p in paragraphs:
        if len(buf) + len(p) <= size:
            buf += ("\n\n" if buf else "") + p
        else:
            if buf:
                chunks.append(buf)
            buf = p[:size]
    if buf:
        chunks.append(buf)
    return chunks[:50]


_STORE = None


def _open_store():
    global _STORE
    import sqlite3
    if _STORE is None:
        # 节点可能在别的线程里执行，连接不能绑死在创建它的线程上
        _STORE = sqlite3.connect(PROJECT_DIR / ".store.db",
                                 check_same_thread=False)
    return _STORE
