"""评测中台接口：数据集、评测任务、逐条结果与人工复核。"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from .. import evaluation

router = APIRouter(prefix="/api/eval", tags=["evaluation"])


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/datasets")
def list_datasets():
    return {"items": evaluation.list_datasets()}


@router.post("/datasets")
def create_dataset(payload: Dict[str, Any]):
    return {"ok": True, "dataset": _wrap(evaluation.save_dataset, payload)}


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    item = evaluation.get_dataset(dataset_id)
    if not item:
        raise HTTPException(404, "数据集不存在")
    return {"dataset": item}


@router.put("/datasets/{dataset_id}")
def update_dataset(dataset_id: str, payload: Dict[str, Any]):
    return {"ok": True,
            "dataset": _wrap(evaluation.save_dataset, payload, dataset_id)}


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str):
    if not evaluation.delete_dataset(dataset_id):
        raise HTTPException(404, "数据集不存在")
    return {"ok": True}


@router.get("/runs")
def list_runs(limit: int = 30):
    return {"items": evaluation.list_runs(limit)}


@router.post("/runs")
async def create_run(payload: Dict[str, Any]):
    run = _wrap(evaluation.create_run, payload)
    await evaluation.start_run_async(run["id"])
    return {"ok": True, "run": run}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    run = evaluation.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测任务不存在")
    run["summary"] = evaluation.summarize(run)
    return {"run": run}


@router.delete("/runs/{run_id}")
def delete_run(run_id: str):
    if not evaluation.delete_run(run_id):
        raise HTTPException(404, "评测任务不存在")
    return {"ok": True}


@router.get("/runs/{run_id}/compare")
def compare_run(run_id: str, base: str):
    """和基线任务对比：谁回归了、谁修好了。"""
    return {"ok": True, "compare": _wrap(evaluation.compare_runs, base, run_id)}


@router.get("/trend")
def eval_trend(canvas_id: str = "", dataset_id: str = "", limit: int = 20):
    return {"items": evaluation.trend(canvas_id, dataset_id, limit)}


@router.patch("/results/{result_id}")
def set_human_verdict(result_id: str, payload: Dict[str, Any]):
    ok = _wrap(evaluation.set_human_verdict, result_id,
               str(payload.get("verdict") or ""), str(payload.get("note") or ""))
    if not ok:
        raise HTTPException(404, "结果不存在")
    return {"ok": True}
