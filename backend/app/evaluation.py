"""评测中台：数据集 → 批量跑画布 → 三层判定（规则 / LLM 裁判 / 人工）。

设计取舍：
- 不去重造执行器，直接调本机 /api/canvases/{id}/run 的 SSE，跑的就是真实链路
- 规则判定的口径和生成项目里的 evals/run.py 保持一致（包含 / 排除 / 延迟），
  这样平台上的结果和项目自带的回归脚本不会打架
- LLM 裁判用「用户中心」配的对话模型，可关；关掉就只有规则判定
- 人工结论（pass/fail）独立存，不改写自动结果，报告里两者并列
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from .config import HOST, PORT
from .db import get_conn, get_setting, now_iso
from .security import decrypt

MAX_CASES = 200
JUDGE_PROMPT = (
    "你是评测裁判。根据【任务】【参考答案要求】【助手输出】给助手输出打 0-10 分。\n"
    "评分只看是否真的完成了任务、信息是否正确，不看文采。\n"
    "只输出 JSON：{\"score\": 数字, \"reason\": \"一句话理由\"}"
)


# --------------------------------------------------------------------------- #
# 数据集
# --------------------------------------------------------------------------- #
def _normalize_case(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    case = {
        "id": str(raw.get("id") or f"case-{index + 1}"),
        "input": str(raw.get("input") or ""),
        "expect_contains": [str(x) for x in (raw.get("expect_contains") or []) if str(x).strip()],
        "expect_not_contains": [str(x) for x in (raw.get("expect_not_contains") or [])
                                if str(x).strip()],
        "max_latency_ms": int(raw.get("max_latency_ms") or 0),
        "tags": [str(x) for x in (raw.get("tags") or [])],
    }
    return case


def list_datasets() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_datasets ORDER BY updated_at DESC").fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            cases = json.loads(item.get("cases") or "[]")
        except json.JSONDecodeError:
            cases = []
        item["case_count"] = len(cases)
        item.pop("cases", None)
        out.append(item)
    return out


def get_dataset(dataset_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM eval_datasets WHERE id = ?", (dataset_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["cases"] = json.loads(item.get("cases") or "[]")
    except json.JSONDecodeError:
        item["cases"] = []
    item["case_count"] = len(item["cases"])
    return item


def save_dataset(payload: Dict[str, Any], dataset_id: str = "") -> Dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("数据集名称不能为空")
    raw_cases = payload.get("cases")
    if isinstance(raw_cases, str):
        # 允许直接贴 JSONL / JSON 文本
        raw_cases = _parse_cases_text(raw_cases)
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("至少需要一条用例")
    if len(raw_cases) > MAX_CASES:
        raise ValueError(f"用例最多 {MAX_CASES} 条")
    cases = [_normalize_case(c, i) for i, c in enumerate(raw_cases) if isinstance(c, dict)]
    if not cases:
        raise ValueError("用例格式不对，每条至少要有一个 input 字段")
    bad = [c["id"] for c in cases if not c["input"].strip()]
    if bad:
        raise ValueError(f"这些用例没有 input：{', '.join(bad[:5])}")

    ts = now_iso()
    payload_json = json.dumps(cases, ensure_ascii=False)
    if dataset_id:
        with get_conn() as conn:
            conn.execute(
                "UPDATE eval_datasets SET name = ?, description = ?, cases = ?, "
                "updated_at = ? WHERE id = ?",
                (name, str(payload.get("description") or ""), payload_json, ts,
                 dataset_id))
        return get_dataset(dataset_id) or {}
    dataset_id = uuid.uuid4().hex[:16]
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO eval_datasets(id,name,description,cases,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (dataset_id, name, str(payload.get("description") or ""), payload_json,
             ts, ts))
    return get_dataset(dataset_id) or {}


def _parse_cases_text(text: str) -> List[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return []
    # 先试整体 JSON 数组
    if text.startswith("["):
        try:
            data = json.loads(text)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            pass
    out: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def delete_dataset(dataset_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM eval_datasets WHERE id = ?", (dataset_id,))
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# 规则判定（口径与项目自带 evals/run.py 一致）
# --------------------------------------------------------------------------- #
def score_case(case: Dict[str, Any], answer: str, latency_ms: float) -> Dict[str, Any]:
    text = answer or ""
    checks: Dict[str, float] = {"non_empty": 1.0 if text.strip() else 0.0}

    contains = case.get("expect_contains") or []
    if contains:
        hit = sum(1 for word in contains if word and word in text)
        checks["contains"] = hit / len(contains)

    forbidden = case.get("expect_not_contains") or []
    if forbidden:
        bad = sum(1 for word in forbidden if word and word in text)
        checks["not_contains"] = 0.0 if bad else 1.0

    limit = int(case.get("max_latency_ms") or 0)
    if limit:
        checks["latency"] = 1.0 if latency_ms <= limit else 0.0

    return {"checks": checks, "passed": all(v >= 1.0 for v in checks.values())}


# --------------------------------------------------------------------------- #
# 跑一条：调本机运行接口
# --------------------------------------------------------------------------- #
def _base_url() -> str:
    host = HOST if HOST not in ("0.0.0.0", "") else "127.0.0.1"
    return f"http://{host}:{PORT}"


async def run_once(canvas_id: str, input_text: str, timeout_s: float = 300.0) -> Dict[str, Any]:
    started = time.time()
    output = ""
    final_output = ""
    error = ""
    usage: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            async with client.stream(
                "POST", f"{_base_url()}/api/canvases/{canvas_id}/run",
                json={"input": input_text}) as resp:
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode("utf-8", "replace")[:300]
                    error = f"运行接口 {resp.status_code}：{detail}"
                else:
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        try:
                            evt = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        kind = evt.get("event")
                        if kind == "final":
                            # final 是节点自己给出的最终输出，最可信
                            final_output = str(evt.get("output") or "")
                        elif kind == "run_end":
                            # run_end 的 output 有时是空的（run.py 兜底补的事件），
                            # 这时退回用 final 里拿到的那份
                            output = str(evt.get("output") or "") or final_output
                            usage = evt.get("usage") or usage
                            if evt.get("status") != "ok":
                                error = str(evt.get("message") or "运行未成功")
                        elif kind == "error":
                            error = str(evt.get("message") or error)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    return {"output": output or final_output, "error": error,
            "usage": usage or {},
            "latency_ms": round((time.time() - started) * 1000, 1)}


# --------------------------------------------------------------------------- #
# LLM 裁判
# --------------------------------------------------------------------------- #
def _judge_cfg() -> Dict[str, Any]:
    return {
        "base_url": get_setting("orchestrator_base_url", "") or "https://api.deepseek.com/v1",
        "model": get_setting("orchestrator_model", "") or "deepseek-chat",
        "api_key": decrypt(get_setting("orchestrator_api_key_cipher", "")),
    }


async def judge_one(case: Dict[str, Any], output: str) -> Dict[str, Any]:
    cfg = _judge_cfg()
    if not cfg["api_key"]:
        return {"score": None, "reason": "没配对话模型 key，跳过 LLM 裁判"}
    base = cfg["base_url"].rstrip("/")
    if not base.endswith("/v1") and "/v1" not in base:
        base += "/v1"
    url = base + "/chat/completions"
    expects = case.get("expect_contains") or []
    user = (
        f"【任务】{case.get('input')}\n"
        f"【参考要求】必须提到：{('、'.join(expects) if expects else '无硬性要求')}\n"
        f"【助手输出】{(output or '')[:4000]}"
    )
    body = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": JUDGE_PROMPT},
                     {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": 300,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url, json=body,
                headers={"Authorization": f"Bearer {cfg['api_key']}",
                         "Content-Type": "application/json"})
            if resp.status_code >= 400:
                return {"score": None,
                        "reason": f"裁判模型返回 {resp.status_code}"}
            data = resp.json()
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    except Exception as exc:  # noqa: BLE001
        return {"score": None, "reason": f"裁判调用失败：{exc}"}

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    try:
        parsed = json.loads(text)
        score = float(parsed.get("score"))
        reason = str(parsed.get("reason") or "")
    except Exception:  # noqa: BLE001
        # 模型没按 JSON 回，退化成拿数字
        import re
        match = re.search(r"(\d+(?:\.\d+)?)", content)
        score = float(match.group(1)) if match else None
        reason = content[:200]
    if score is not None:
        score = max(0.0, min(10.0, score))
    return {"score": score, "reason": reason}


# --------------------------------------------------------------------------- #
# 评测任务
# --------------------------------------------------------------------------- #
def _update_run(run_id: str, **fields: Any) -> None:
    sets = [f"{k} = ?" for k in fields]
    values = list(fields.values())
    values.append(run_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE eval_runs SET {', '.join(sets)} WHERE id = ?", values)


def create_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    canvas_id = str(payload.get("canvas_id") or "").strip()
    dataset_id = str(payload.get("dataset_id") or "").strip()
    if not canvas_id:
        raise ValueError("要选一张画布")
    if not dataset_id:
        raise ValueError("要选一个数据集")
    dataset = get_dataset(dataset_id)
    if not dataset:
        raise ValueError("数据集不存在")
    with get_conn() as conn:
        canvas = conn.execute(
            "SELECT id, name FROM canvases WHERE id = ?", (canvas_id,)).fetchone()
    if not canvas:
        raise ValueError("画布不存在")

    use_judge = 1 if payload.get("use_judge") else 0
    repeat = max(1, min(int(payload.get("repeat") or 1), 5))
    run_id = uuid.uuid4().hex[:16]
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO eval_runs(id,canvas_id,canvas_name,dataset_id,dataset_name,"
            "status,judge_model,use_judge,repeat,total,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, canvas_id, canvas["name"], dataset_id, dataset["name"],
             "pending", _judge_cfg().get("model") or "", use_judge, repeat,
             len(dataset["cases"]) * repeat, ts))
    return get_run(run_id) or {}


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    with get_conn() as conn:
        results = conn.execute(
            "SELECT * FROM eval_results WHERE run_id = ? ORDER BY created_at",
            (run_id,)).fetchall()
    item["results"] = [_result_dict(r) for r in results]
    return item


def _result_dict(row) -> Dict[str, Any]:
    item = dict(row)
    for key in ("rule_detail", "usage"):
        try:
            item[key] = json.loads(item.get(key) or "{}")
        except json.JSONDecodeError:
            item[key] = {}
    item["rule_passed"] = bool(item.get("rule_passed"))
    return item


def trend(canvas_id: str = "", dataset_id: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """历次评测的通过率曲线，用来观察长期退化。"""
    sql = ("SELECT id,canvas_name,dataset_name,total,passed,status,created_at "
           "FROM eval_runs WHERE status = 'done'")
    params: List[Any] = []
    if canvas_id:
        sql += " AND canvas_id = ?"
        params.append(canvas_id)
    if dataset_id:
        sql += " AND dataset_id = ?"
        params.append(dataset_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = [dict(r) for r in rows]
    for item in out:
        total = int(item.get("total") or 0)
        item["pass_rate"] = round(int(item.get("passed") or 0) / total, 3) if total else 0
    return list(reversed(out))


def list_runs(limit: int = 30) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


async def execute_run(run_id: str) -> None:
    """跑完一整个评测任务。失败不抛出，写进 run.error。

    repeat > 1 时，每条用例重复跑多次（用来测非确定性），
    结果按 `case_id#attempt` 区分，统计时再按 case_id 聚合。
    """
    run = get_run(run_id)
    if not run:
        return
    dataset = get_dataset(run["dataset_id"])
    if not dataset:
        _update_run(run_id, status="failed", error="数据集已被删除",
                    finished_at=now_iso())
        return
    cases = dataset.get("cases") or []
    repeat = max(1, min(int(run.get("repeat") or 1), 5))
    total_units = len(cases) * repeat
    _update_run(run_id, status="running", error="", done=0, passed=0,
                total=total_units)

    passed = 0
    done = 0
    try:
        for case in cases:
            for attempt in range(1, repeat + 1):
                outcome = await run_once(run["canvas_id"], case["input"])
                rule = score_case(case, outcome["output"], outcome["latency_ms"])
                llm_score: Optional[float] = None
                llm_reason = ""
                if run.get("use_judge"):
                    judged = await judge_one(case, outcome["output"])
                    llm_score = judged.get("score")
                    llm_reason = str(judged.get("reason") or "")

                if rule["passed"]:
                    passed += 1
                done += 1
                case_label = (case["id"] if repeat == 1
                              else f"{case['id']}#{attempt}")
                with get_conn() as conn:
                    conn.execute(
                        "INSERT INTO eval_results(id,run_id,case_id,input,output,"
                        "latency_ms,error,rule_passed,rule_detail,llm_score,"
                        "llm_reason,usage,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (uuid.uuid4().hex[:16], run_id, case_label, case["input"],
                         outcome["output"], outcome["latency_ms"], outcome["error"],
                         1 if rule["passed"] else 0,
                         json.dumps({"checks": rule["checks"],
                                     "tags": case.get("tags") or [],
                                     "case": case["id"]}, ensure_ascii=False),
                         llm_score, llm_reason,
                         json.dumps(outcome.get("usage") or {}, ensure_ascii=False),
                         now_iso()))
                _update_run(run_id, done=done, passed=passed)

        _update_run(run_id, status="done", finished_at=now_iso())
    except Exception as exc:  # noqa: BLE001
        _update_run(run_id, status="failed", error=str(exc)[:300],
                    finished_at=now_iso())


async def start_run_async(run_id: str) -> None:
    """后台跑；调用方不等待。"""
    asyncio.create_task(execute_run(run_id))


def set_human_verdict(result_id: str, verdict: str, note: str = "") -> bool:
    if verdict not in ("", "pass", "fail"):
        raise ValueError("verdict 只能是 pass / fail / 空")
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE eval_results SET human_verdict = ?, human_note = ? WHERE id = ?",
            (verdict, note or "", result_id))
    return cur.rowcount > 0


def delete_run(run_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM eval_runs WHERE id = ?", (run_id,))
        conn.execute("DELETE FROM eval_results WHERE run_id = ?", (run_id,))
    return cur.rowcount > 0


def _percentile(values: List[float], pct: float) -> float:
    """线性插值分位数；空列表返回 0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * pct
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    weight = pos - low
    return float(ordered[low] * (1 - weight) + ordered[high] * weight)


def summarize(run: Dict[str, Any]) -> Dict[str, Any]:
    """报告口径：规则/LLM/人工三套结论并列，再加性能、成本、失败分类与稳定性。

    刻意不把 token 折算成钱——单价随厂商和模型变动，写死会给出假数字。
    这里只报真实 token 用量，要算钱请按自己谈的单价乘。
    """
    results = run.get("results") or []
    total = len(results)
    empty = {
        "total": 0, "rule_passed": 0, "rule_pass_rate": 0,
        "judge_avg": None, "judge_count": 0,
        "human_reviewed": 0, "human_passed": 0, "human_pass_rate": None,
        "latency": {"avg": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0},
        "tokens": {"prompt": 0, "completion": 0, "total": 0, "calls": 0},
        "failures": {"run_error": 0, "rule_failed": 0, "timeout": 0},
        "by_tag": {}, "stability": None,
    }
    if not total:
        return empty

    rule_passed = sum(1 for r in results if r.get("rule_passed"))
    judged = [r["llm_score"] for r in results if r.get("llm_score") is not None]
    reviewed = [r for r in results if r.get("human_verdict")]
    human_passed = sum(1 for r in reviewed if r.get("human_verdict") == "pass")

    latencies = [float(r.get("latency_ms") or 0) for r in results]

    tokens = {"prompt": 0, "completion": 0, "total": 0, "calls": 0}
    for r in results:
        usage = r.get("usage") or {}
        if not isinstance(usage, dict):
            continue
        tokens["prompt"] += int(usage.get("prompt_tokens") or 0)
        tokens["completion"] += int(usage.get("completion_tokens") or 0)
        tokens["total"] += int(usage.get("total_tokens") or 0)
        tokens["calls"] += int(usage.get("calls") or 0)

    # 失败分类：跑挂了 / 规则不过 / 超时，三类问题根因完全不同
    failures = {"run_error": 0, "rule_failed": 0, "timeout": 0}
    for r in results:
        if str(r.get("error") or "").strip():
            if "timeout" in str(r["error"]).lower() or "超时" in str(r["error"]):
                failures["timeout"] += 1
            else:
                failures["run_error"] += 1
        elif not r.get("rule_passed"):
            failures["rule_failed"] += 1

    # 按 tags 分组
    by_tag: Dict[str, Dict[str, Any]] = {}
    for r in results:
        detail = r.get("rule_detail") or {}
        tags = detail.get("tags") if isinstance(detail, dict) else None
        for tag in (tags or ["未打标"]):
            slot = by_tag.setdefault(str(tag), {"total": 0, "passed": 0})
            slot["total"] += 1
            if r.get("rule_passed"):
                slot["passed"] += 1
    for slot in by_tag.values():
        slot["rate"] = round(slot["passed"] / slot["total"], 3) if slot["total"] else 0

    # 稳定性：同一用例多次跑，结论是否一致
    stability = None
    grouped: Dict[str, List[bool]] = {}
    for r in results:
        detail = r.get("rule_detail") or {}
        base = detail.get("case") if isinstance(detail, dict) else None
        base = str(base or str(r.get("case_id") or "").split("#")[0])
        grouped.setdefault(base, []).append(bool(r.get("rule_passed")))
    multi = {k: v for k, v in grouped.items() if len(v) > 1}
    if multi:
        consistent = sum(1 for v in multi.values() if len(set(v)) == 1)
        stability = {
            "repeated_cases": len(multi),
            "consistent_cases": consistent,
            "consistency_rate": round(consistent / len(multi), 3),
        }

    return {
        "total": total,
        "rule_passed": rule_passed,
        "rule_pass_rate": round(rule_passed / total, 3),
        "judge_avg": round(sum(judged) / len(judged), 2) if judged else None,
        "judge_count": len(judged),
        "human_reviewed": len(reviewed),
        "human_passed": human_passed,
        "human_pass_rate": (round(human_passed / len(reviewed), 3)
                            if reviewed else None),
        "latency": {
            "avg": round(sum(latencies) / total, 1),
            "p50": round(_percentile(latencies, 0.5), 1),
            "p95": round(_percentile(latencies, 0.95), 1),
            "p99": round(_percentile(latencies, 0.99), 1),
            "max": round(max(latencies), 1),
        },
        "tokens": tokens,
        "failures": failures,
        "by_tag": by_tag,
        "stability": stability,
    }


def compare_runs(base_id: str, target_id: str) -> Dict[str, Any]:
    """基线对比：哪些用例从过变成不过（回归），哪些从不过变成过（修复）。"""
    base = get_run(base_id)
    target = get_run(target_id)
    if not base or not target:
        raise ValueError("基线或目标任务不存在")

    def index(run: Dict[str, Any]) -> Dict[str, bool]:
        out: Dict[str, bool] = {}
        for r in run.get("results") or []:
            detail = r.get("rule_detail") or {}
            key = (detail.get("case") if isinstance(detail, dict) else None) or r["case_id"]
            # 同一用例多次跑：任一次过就算过（宽松口径，回归更容易暴露）
            out[str(key)] = out.get(str(key), False) or bool(r.get("rule_passed"))
        return out

    b, t = index(base), index(target)
    common = sorted(set(b) & set(t))
    regressed = [k for k in common if b[k] and not t[k]]
    fixed = [k for k in common if not b[k] and t[k]]
    return {
        "base": {"id": base["id"], "created_at": base["created_at"],
                 "pass_rate": round(sum(b.values()) / len(b), 3) if b else 0},
        "target": {"id": target["id"], "created_at": target["created_at"],
                   "pass_rate": round(sum(t.values()) / len(t), 3) if t else 0},
        "common_cases": len(common),
        "regressed": regressed,
        "fixed": fixed,
        "only_in_base": sorted(set(b) - set(t)),
        "only_in_target": sorted(set(t) - set(b)),
    }
