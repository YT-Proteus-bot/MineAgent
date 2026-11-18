"""执行沙箱：节点里的 shell / exec_python 都走这里，只有一处需要审。

模式由 MINEAGENT_SANDBOX 决定（画布「服务设置 → 安全 → 默认执行沙箱」会写进 settings）：

    none        不限制：命令直接在项目目录里跑（只给本地开发用）
    restricted  受限（默认）：项目目录 + 密钥清理 + 超时 + 输出上限
    container   容器隔离：在 docker 里跑，无网络、只读根、限内存/CPU/PID

一致原则：**宁可报错，也不要悄悄降级**。选了 container 却没装 docker，
就抛 RuntimeError 让人看见，而不是照常在宿主上执行。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_DIR = Path(__file__).resolve().parent
# 这些环境变量一律不传给被执行的子进程（模型 key / 中台 token / 服务 key）
_SECRET_PREFIXES = ("MINEAGENT_KEY_", "MINEAGENT_API_KEY", "MINEAGENT_SERVICE_KEY",
                    "MINEAGENT_DATA_TOKEN", "MINEAGENT_EVAL_TOKEN", "OPENAI_API_KEY",
                    "ANTHROPIC_API_KEY", "AWS_", "AZURE_")
OUTPUT_CAP = 4000
CONTAINER_IMAGE = os.environ.get("MINEAGENT_SANDBOX_IMAGE", "python:3.11-slim")


def mode() -> str:
    return (os.environ.get("MINEAGENT_SANDBOX") or "restricted").strip().lower()


def describe() -> Dict[str, object]:
    """给 /ready 和自检用：当前模式、是否真的可用。"""
    current = mode()
    return {
        "mode": current,
        "docker": shutil.which("docker") is not None,
        "usable": current in ("none", "restricted", "container")
                  and (current != "container" or shutil.which("docker") is not None),
    }


def _clean_env(extra: Dict[str, str] | None = None) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not any(k.upper().startswith(p) for p in _SECRET_PREFIXES)}
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def _cap(text: str) -> str:
    return text[-OUTPUT_CAP:]


def _run(cmd: List[str], timeout: float, shell: bool = False, cwd: str | None = None,
         stdin_text: str | None = None) -> Dict[str, str]:
    try:
        proc = subprocess.run(
            cmd, shell=shell, cwd=cwd, input=stdin_text,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", env=_clean_env(),
        )
    except subprocess.TimeoutExpired:
        return {"code": "timeout", "stdout": "", "stderr": f"执行超时（>{timeout:g}s）"}
    except FileNotFoundError as exc:
        return {"code": "missing", "stdout": "", "stderr": str(exc)}
    return {"code": str(proc.returncode), "stdout": _cap(proc.stdout or ""),
            "stderr": _cap(proc.stderr or "")}


def _docker_prefix() -> List[str]:
    if shutil.which("docker") is None:
        raise RuntimeError(
            "沙箱模式是 container，但这台机器上找不到 docker。"
            "要么装好 docker，要么把 MINEAGENT_SANDBOX 改成 restricted。"
        )
    return [
        "docker", "run", "--rm",
        "--network=none",          # 容器里不允许出网
        "--read-only",             # 根文件系统只读
        "--memory=512m", "--memory-swap=512m",
        "--pids-limit=128",
        "--cpus=1",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "-v", f"{PROJECT_DIR}:/work:rw",
        "-w", "/work",
    ]


def run_shell(command: str, timeout: float = 60.0) -> Dict[str, str]:
    """执行一条 shell 命令。返回 {code, stdout, stderr}。"""
    current = mode()
    if current in ("off", "disabled"):
        raise PermissionError("执行沙箱已关闭（MINEAGENT_SANDBOX=off），shell 被禁止")
    if current == "container":
        return _run(_docker_prefix() + [CONTAINER_IMAGE, "sh", "-c", command], timeout)
    # none / restricted：都在项目目录里跑；restricted 额外清掉密钥、限时、截断输出
    return _run(command, timeout, shell=True, cwd=str(PROJECT_DIR))


def run_python(code: str, timeout: float = 30.0) -> Dict[str, str]:
    """执行一段 Python 代码。返回 {stdout, stderr}。"""
    current = mode()
    if current in ("off", "disabled"):
        raise PermissionError("执行沙箱已关闭（MINEAGENT_SANDBOX=off），exec_python 被禁止")
    if current == "container":
        return _run(_docker_prefix() + [CONTAINER_IMAGE, "python", "-"], timeout,
                    stdin_text=code)
    tmp = PROJECT_DIR / ".sandbox_snippet.py"
    try:
        tmp.write_text(code, encoding="utf-8")
        out = _run([sys.executable, str(tmp)], timeout, cwd=str(PROJECT_DIR))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return {"stdout": out["stdout"], "stderr": out["stderr"]}
