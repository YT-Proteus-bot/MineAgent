"""全局路径与运行配置。"""
from __future__ import annotations

import os
from pathlib import Path

# 仓库根目录：MineAgent/
BASE_DIR = Path(__file__).resolve().parents[2]

BACKEND_DIR = BASE_DIR / "backend"
DATA_DIR = BACKEND_DIR / "data"
PROJECTS_DIR = BASE_DIR / "projects"
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"

DB_PATH = DATA_DIR / "mineagent.db"
MASTER_KEY_PATH = DATA_DIR / "master.key"
RUN_LOG_DIR = DATA_DIR / "runs"
# 画布背景图上传目录（不进 git）
BACKGROUND_DIR = DATA_DIR / "backgrounds"

HOST = os.environ.get("MINEAGENT_HOST", "0.0.0.0")
PORT = int(os.environ.get("MINEAGENT_PORT", "8000"))

# 运行子进程的超时时间（秒）
RUN_TIMEOUT = int(os.environ.get("MINEAGENT_RUN_TIMEOUT", "600"))
# 背景图大小上限（字节）
MAX_BACKGROUND_BYTES = 12 * 1024 * 1024


def ensure_dirs() -> None:
    for d in (DATA_DIR, PROJECTS_DIR, RUN_LOG_DIR, BACKGROUND_DIR):
        d.mkdir(parents=True, exist_ok=True)
