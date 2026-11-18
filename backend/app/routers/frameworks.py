"""框架运行环境管理接口。

每个「可运行框架」有自己的 venv（MetaGPT 之类和主环境不兼容），
这里提供状态查询与安装/删除，前端在框架下拉和运行面板里展示。
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from .. import framework_env

router = APIRouter(prefix="/api/frameworks", tags=["frameworks"])


@router.get("/envs")
def list_envs() -> List[Dict[str, Any]]:
    return framework_env.all_status()


@router.get("/{framework}/env")
def get_env(framework: str) -> Dict[str, Any]:
    if framework not in framework_env.FRAMEWORK_PACKAGES:
        raise HTTPException(status_code=404, detail=f"未知框架：{framework}")
    return framework_env.status(framework)


@router.post("/{framework}/env")
def install_env(framework: str) -> Dict[str, Any]:
    """创建隔离环境并安装依赖。同步执行，可能要几分钟。"""
    if framework not in framework_env.FRAMEWORK_PACKAGES:
        raise HTTPException(status_code=404, detail=f"未知框架：{framework}")
    result = framework_env.create(framework)
    result["status"] = framework_env.status(framework)
    return result


@router.delete("/{framework}/env")
def remove_env(framework: str) -> Dict[str, Any]:
    if framework not in framework_env.FRAMEWORK_PACKAGES:
        raise HTTPException(status_code=404, detail=f"未知框架：{framework}")
    result = framework_env.remove(framework)
    result["status"] = framework_env.status(framework)
    return result
