"""HMAC 签名器 — 镜像 tools/src/connectors/hmacSigner.ts(防重放 ≤300s)。"""

from __future__ import annotations

import hashlib
import hmac
import time


def canonical_string(method: str, path: str, timestamp: str, nonce: str, body_sha256: str) -> str:
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_sha256}"


def sign(secret: str, method: str, path: str, timestamp: str, nonce: str, body: str) -> str:
    body_sha = hashlib.sha256((body or "").encode()).hexdigest()
    message = canonical_string(method, path, timestamp, nonce, body_sha).encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(
    secret: str,
    signature: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: str,
    max_skew_seconds: int = 300,
) -> bool:
    """恒定时间比较 + 时间窗校验(镜像 TS crypto.timingSafeEqual + 防重放窗口)。"""
    try:
        if abs(int(time.time() * 1000) - int(timestamp)) > max_skew_seconds * 1000:
            return False
    except (TypeError, ValueError):
        return False
    expected = sign(secret, method, path, timestamp, nonce, body)
    return hmac.compare_digest(expected, signature)
