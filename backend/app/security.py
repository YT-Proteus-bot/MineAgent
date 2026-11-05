"""本地密钥加密工具。

约定：
- 主密钥保存在 backend/data/master.key（首次运行时自动生成，仅本机可读）。
- 用户配置的模型 api key / 全局 api key 一律以密文落库，接口永不回显明文，
  只回显 `sk-****abcd` 形式的掩码。
- 算法：HMAC-SHA256 计数器模式生成密钥流，密文前附 nonce 与 HMAC 校验标签。
  这是零依赖实现，仅用于本地单机场景，不用于对外传输。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path

from .config import MASTER_KEY_PATH

_KEY: bytes | None = None


def _master_key() -> bytes:
    global _KEY
    if _KEY is not None:
        return _KEY
    path: Path = MASTER_KEY_PATH
    if path.exists():
        raw = path.read_bytes().strip()
        _KEY = base64.urlsafe_b64decode(raw)
    else:
        key = os.urandom(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.urlsafe_b64encode(key))
        _KEY = key
    return _KEY


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(out[:length])


def encrypt(plain: str) -> str:
    if plain is None:
        return ""
    data = plain.encode("utf-8")
    key = _master_key()
    nonce = os.urandom(16)
    stream = _keystream(key, nonce, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + tag + cipher).decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        blob = base64.urlsafe_b64decode(token.encode("ascii"))
    except Exception:
        return ""
    if len(blob) < 32:
        return ""
    nonce, tag, cipher = blob[:16], blob[16:32], blob[32:]
    key = _master_key()
    expect = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expect):
        return ""
    stream = _keystream(key, nonce, len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8", "replace")


def mask(secret: str) -> str:
    """把密钥变成 sk-****abcd 形式用于界面回显。"""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:3]}****{secret[-4:]}"
