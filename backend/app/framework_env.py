"""每个 Agent 框架一个独立虚拟环境。

为什么要隔离：MetaGPT 会把 pydantic 降到 1.x、把 langchain 降到 0.0.231，
和当前后端（pydantic 2.x / langchain 1.x）完全不兼容。直接装进主 venv 会把
MineAgent 自己弄坏。所以每个「可运行框架」有自己的 venv：

    backend/data/fw-envs/<framework>/Scripts/python.exe   (Windows)
    backend/data/fw-envs/<framework>/bin/python           (POSIX)

平台运行某个画布时，按它的 framework 选解释器，各跑各的。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DATA_DIR

ENV_ROOT = DATA_DIR / "fw-envs"

# 每个框架需要装什么。版本按「能跑通」而不是「最新」来钉。
FRAMEWORK_PACKAGES: Dict[str, List[str]] = {
    "langchain": ["langchain>=1.0", "langgraph>=1.0", "langchain-openai>=1.0"],
    "autogen": ["autogen-agentchat>=0.4.0", "autogen-ext[openai]>=0.4.0"],
    "crewai": ["crewai>=0.60.0"],
    "metagpt": ["metagpt>=0.8.0"],
    "agno": ["agno", "langchain>=1.0", "langchain-openai>=1.0",
             "langchain-core>=1.0"],
    # 节点块用 langchain 的 @tool / create_agent，编排用 smolagents
    "smolagents": ["smolagents>=1.0", "langchain>=1.0", "langchain-openai>=1.0",
                   "langchain-core>=1.0"],
    "semantic_kernel": ["semantic-kernel", "openai", "langchain>=1.0",
                        "langchain-openai>=1.0", "langchain-core>=1.0"],
    "openai_agents": ["openai-agents", "openai", "langchain>=1.0",
                      "langchain-openai>=1.0", "langchain-core>=1.0"],
    "dify": [],
}

# 判断「装好了」时探测的模块名
FRAMEWORK_MODULES: Dict[str, str] = {
    "langchain": "langgraph",
    "autogen": "autogen_agentchat",
    "crewai": "crewai",
    "metagpt": "metagpt",
    "agno": "agno",
    "smolagents": "smolagents",
    "semantic_kernel": "semantic_kernel",
    "openai_agents": "agents",
    "dify": "",
}

# 这些框架用隔离环境；其余跑在主 venv 里
ISOLATED = {"metagpt", "agno", "smolagents", "semantic_kernel", "openai_agents"}


def env_dir(framework: str) -> Path:
    return ENV_ROOT / framework


def interpreter(framework: str) -> Optional[Path]:
    """返回这个框架该用的 python；没有隔离环境时返回 None（用主解释器）。"""
    if framework not in ISOLATED:
        return None
    base = env_dir(framework)
    for rel in ("Scripts/python.exe", "bin/python", "Scripts/python", "bin/python3"):
        candidate = base / rel
        if candidate.exists():
            return candidate
    return None


def is_ready(framework: str) -> bool:
    """隔离环境是否已经装好且依赖可导入。"""
    if framework not in ISOLATED:
        return True
    python = interpreter(framework)
    if python is None:
        return False
    return _has_module(python, FRAMEWORK_MODULES.get(framework, ""))


def _has_module(python: Path, module: str) -> bool:
    if not module:
        return True
    try:
        proc = subprocess.run(
            [str(python), "-c", f"import {module}"],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace")
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def status(framework: str) -> Dict[str, Any]:
    """给接口和前端用的状态。"""
    isolated = framework in ISOLATED
    if isolated:
        python = interpreter(framework)
        ready = python is not None and _has_module(
            python, FRAMEWORK_MODULES.get(framework, ""))
    else:
        python = None
        ready = _has_module_in_main(FRAMEWORK_MODULES.get(framework, ""))
    return {
        "framework": framework,
        "isolated": isolated,
        "required": framework in FRAMEWORK_PACKAGES,
        "ready": ready,
        "path": str(env_dir(framework)) if isolated else "",
        "interpreter": str(python) if python else sys.executable,
        "packages": FRAMEWORK_PACKAGES.get(framework, []),
    }


def _has_module_in_main(module: str) -> bool:
    """主环境里能不能 import 这个模块。"""
    if not module:
        return True
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def create(framework: str, *, timeout: float = 1800.0) -> Dict[str, Any]:
    """建 venv 并装这个框架的依赖。同步执行，可能要几分钟。"""
    if framework not in ISOLATED:
        return {"ok": True, "message": f"{framework} 使用主环境，无需单独安装"}
    packages = FRAMEWORK_PACKAGES.get(framework, [])
    if not packages:
        return {"ok": False, "message": f"没有为 {framework} 配置依赖清单"}

    base = env_dir(framework)
    python = interpreter(framework)
    if python is None:
        ENV_ROOT.mkdir(parents=True, exist_ok=True)
        proc = _run([sys.executable, "-m", "venv", str(base)], timeout=300)
        if proc.returncode != 0:
            return {"ok": False, "message": "创建虚拟环境失败",
                    "detail": (proc.stderr or proc.stdout or "")[-1500:]}
        python = interpreter(framework)
        if python is None:
            return {"ok": False, "message": "虚拟环境创建后找不到 python"}

    # pip 先自己升级一次，老 pip 解析不了新的依赖标记
    _run([str(python), "-m", "pip", "install", "--upgrade", "pip", "-q"],
         timeout=300)

    started = time.time()
    proc = _run([str(python), "-m", "pip", "install", "--no-input", *packages],
                timeout=timeout)
    elapsed = int(time.time() - started)
    if proc.returncode != 0:
        return {"ok": False, "message": f"安装依赖失败（{elapsed}s）",
                "detail": (proc.stderr or proc.stdout or "")[-2000:]}

    ok = _has_module(python, FRAMEWORK_MODULES.get(framework, ""))
    return {
        "ok": ok,
        "message": (f"{framework} 环境已就绪（{elapsed}s）" if ok
                    else f"依赖装完了，但 {FRAMEWORK_MODULES.get(framework)} 仍无法导入"),
        "detail": (proc.stdout or "")[-1500:],
        "interpreter": str(python),
    }


def remove(framework: str) -> Dict[str, Any]:
    base = env_dir(framework)
    if not base.exists():
        return {"ok": True, "message": "没有可删除的环境"}
    shutil.rmtree(base, ignore_errors=True)
    return {"ok": True, "message": f"已删除 {framework} 的隔离环境"}


def all_status() -> List[Dict[str, Any]]:
    return [status(fw) for fw in FRAMEWORK_PACKAGES]


def _run(cmd: List[str], timeout: float) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", env=env)
