"""全局设置（编排用 key）与连通性测试。"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict

from fastapi import APIRouter

from ..db import get_setting, set_setting
from ..schemas import GlobalSettings
from ..security import decrypt, encrypt, mask

router = APIRouter(prefix="/api/settings", tags=["settings"])


def current_settings() -> GlobalSettings:
    cipher = get_setting("orchestrator_api_key_cipher", "")
    return GlobalSettings(
        orchestrator_provider=get_setting("orchestrator_provider", "openai"),
        orchestrator_base_url=get_setting("orchestrator_base_url", "https://api.openai.com/v1"),
        orchestrator_model=get_setting("orchestrator_model", "gpt-4o-mini"),
        orchestrator_api_key=None,
        orchestrator_api_key_mask=mask(decrypt(cipher)) if cipher else "",
    )


@router.get("", response_model=GlobalSettings)
def read_settings():
    return current_settings()


@router.put("", response_model=GlobalSettings)
def write_settings(payload: GlobalSettings):
    set_setting("orchestrator_provider", payload.orchestrator_provider or "openai")
    set_setting("orchestrator_base_url", payload.orchestrator_base_url or "")
    set_setting("orchestrator_model", payload.orchestrator_model or "")
    if payload.orchestrator_api_key is not None:
        key = payload.orchestrator_api_key.strip()
        set_setting("orchestrator_api_key_cipher", encrypt(key) if key else "")
    return current_settings()


def _normalize_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/") or "https://api.openai.com/v1"
    if base.endswith("/chat/completions"):
        return base
    if not base.endswith("/v1") and "/v1" not in base:
        base += "/v1"
    return base + "/chat/completions"


@router.post("/test")
def test_connection(payload: Dict[str, Any]):
    """用给定（或已存）配置发一次最小请求，验证 key 与地址可用。"""
    api_key = payload.get("api_key") or decrypt(get_setting("orchestrator_api_key_cipher", ""))
    base_url = payload.get("base_url") or get_setting("orchestrator_base_url", "")
    model = payload.get("model") or get_setting("orchestrator_model", "gpt-4o-mini")
    if not api_key:
        return {"ok": False, "message": "还没有配置 API Key"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    req = urllib.request.Request(
        _normalize_url(base_url),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"ok": True, "message": f"连接成功，模型回复：{str(text)[:60]}"}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "message": f"HTTP {exc.code}：{detail}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"连接失败：{exc}"}
