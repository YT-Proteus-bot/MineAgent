"""Provider 适配层的公共设施。

三条铁律：
1. 一律懒加载：runtime_sdk 会被复制进每个生成的项目，不能因为引入了
   「支持所有向量库」就把几十个 SDK 变成硬依赖。
2. 缺库要能照做：ProviderUnavailable 带 pip 命令，节点把它转成可读提示。
3. 只用标准库做 HTTP：生成的项目可能没装 httpx/requests。

后端平台侧同样复用这里的实现，保证「平台内跑」和「独立部署跑」行为一致。
"""
from __future__ import annotations

import importlib
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

from .errors import ProviderCallError, ProviderConfigError, ProviderUnavailable

_UA = "MineAgent/1.0 (+providers)"
_IMPORT_CACHE: Dict[str, Any] = {}


def lazy_import(module: str, pip_name: str = "", *, attr: str = "",
                extra: str = "") -> Any:
    """按需 import；缺库时抛一个带安装命令的 ProviderUnavailable。"""
    key = f"{module}:{attr}"
    if key in _IMPORT_CACHE:
        return _IMPORT_CACHE[key]
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:
        raise ProviderUnavailable(module, pip_name or module, extra=extra) from exc
    target = getattr(mod, attr) if attr else mod
    _IMPORT_CACHE[key] = target
    return target


def has_module(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except Exception:  # noqa: BLE001
        return False


def http_json(url: str, payload: Optional[Dict[str, Any]] = None, *,
              headers: Optional[Dict[str, str]] = None, method: str = "POST",
              timeout: float = 30.0, raw_body: Optional[bytes] = None) -> Any:
    """发一次 JSON 请求并解析响应。

    刻意不设 Accept-Encoding: gzip —— 标准库不会自动解压，设了反而会拿到乱码。
    """
    body: Optional[bytes]
    if raw_body is not None:
        body = raw_body
    elif payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    else:
        body = None

    hdrs = {
        "Accept": "application/json",
        "User-Agent": _UA,
    }
    if body is not None:
        hdrs["Content-Type"] = "application/json; charset=utf-8"
    hdrs.update(headers or {})

    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        raise ProviderCallError(f"请求 {url} 失败", status=exc.code, detail=detail,
                                hint=_http_hint(exc.code)) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ProviderCallError(f"连不上 {url}：{reason}",
                                hint="检查地址、端口、网络，以及服务是否已启动") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise ProviderCallError(f"请求超时（{timeout}s）",
                                hint="调大超时，或检查服务负载") from exc
    except Exception as exc:  # noqa: BLE001
        raise ProviderCallError(f"请求异常：{exc}") from exc

    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderCallError("响应不是合法 JSON", detail=text) from exc


def _http_hint(status: int) -> str:
    if status == 401:
        return "鉴权失败：检查 API Key / Token 是否正确、是否过期"
    if status == 403:
        return "无权访问：检查 Key 权限范围，或该接口是否需要额外开通"
    if status == 404:
        return "地址或模型名不存在：检查 Base URL 是否少了 /v1，模型名是否拼错"
    if status == 429:
        return "触发限流：降低 batch_size 或稍后重试"
    if status >= 500:
        return "服务端错误：稍后重试，或换一个可用区域"
    return ""


def require(cfg: Dict[str, Any], key: str, *, label: str = "") -> Any:
    """取一个必填配置，缺了就抛可读错误。"""
    value = cfg.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ProviderConfigError(f"缺少配置项：{label or key}", hint=f"在「{label or key}」里填写后重试")
    return value


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def join_url(base: str, path: str) -> str:
    """拼 URL：base 末尾的 / 和 path 开头的 / 都收敛掉。"""
    base = (base or "").strip().rstrip("/")
    path = (path or "").lstrip("/")
    return f"{base}/{path}" if path else base


def split_host_port(value: str, default_port: int) -> tuple[str, int]:
    """从 host:port 或 URL 里拆出主机和端口。"""
    raw = (value or "").strip()
    if "://" not in raw:
        raw = f"//{raw}"
    parsed = urllib.parse.urlsplit(raw)
    host = parsed.hostname or "127.0.0.1"
    return host, parsed.port or default_port


def batches(items: Iterable[Any], size: int) -> Iterable[List[Any]]:
    """按 batch_size 切片，size<=0 时整批一次。"""
    buf: List[Any] = []
    limit = max(1, size)
    for item in items:
        buf.append(item)
        if len(buf) >= limit:
            yield buf
            buf = []
    if buf:
        yield buf


# --------------------------------------------------------------------------- #
# 向量库适配器共用的小工具
# --------------------------------------------------------------------------- #
def norm_metric(metric: str) -> str:
    """把各种叫法归一到 cosine / dot / euclidean。"""
    m = (metric or "cosine").strip().lower()
    if m in ("cosine", "cos", "cosine_similarity"):
        return "cosine"
    if m in ("dot", "ip", "dotproduct", "inner_product", "dot_product"):
        return "dot"
    if m in ("l2", "euclid", "euclidean", "l2_norm", "l2-squared"):
        return "euclidean"
    return "cosine"


def dist_to_score(distance: float, metric: str) -> float:
    """把「距离」统一换成「越大越相似」的分数。"""
    if metric == "cosine":
        return 1.0 - float(distance)
    if metric == "dot":
        return float(distance)
    return 1.0 / (1.0 + max(0.0, float(distance)))


def vec_to_literal(vec: List[float]) -> str:
    """[1,2,3] 形式的向量字面量，给 pgvector / mysql 之类用。"""
    return "[" + ",".join(f"{float(x):.8g}" for x in vec) + "]"


def safe_ident(name: str, max_len: int = 60) -> str:
    """把集合名压成只含字母数字下划线的标识符（各库命名限制不同）。"""
    out = []
    for ch in str(name or "default"):
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    ident = "".join(out).strip("_") or "default"
    if ident[0].isdigit():
        ident = "c_" + ident
    return ident[:max_len]


def load_json_ish(raw: Any) -> Any:
    if raw is None:
        return {}
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}


def match_where(meta: Dict[str, Any], where: Dict[str, Any]) -> bool:
    """统一的元数据过滤语义：等值，或 {"$in": [...]} / {"$ne": ...}。"""
    data = meta or {}
    for key, expect in (where or {}).items():
        actual = data.get(key)
        if isinstance(expect, dict):
            if "$in" in expect and actual not in expect["$in"]:
                return False
            if "$ne" in expect and actual == expect["$ne"]:
                return False
        elif actual != expect:
            return False
    return True
