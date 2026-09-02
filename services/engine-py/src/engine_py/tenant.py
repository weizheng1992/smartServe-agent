"""租户品牌展示与响应清洗 — 对齐 packages/types/src/config.ts 与 finish.node.ts。"""

from __future__ import annotations

import re

_PLACEHOLDER_RE = re.compile(r"\[([a-zA-Z0-9_-]+)\]")


def get_merchant_display_name(business_id: str | None) -> str:
    clean = (business_id or "ecommerce").lower()
    if clean == "aurora":
        return "极光潮品官方旗舰店"
    if clean == "adidas":
        return "Adidas 官方旗舰店"
    if clean == "nike":
        return "Nike 官方旗舰店"
    if clean == "ecommerce":
        return "官方综合商城"
    return f"{clean[:1].upper()}{clean[1:]} 官方商城"


def sanitize_tenant_response(raw_content: str, tenant_id: str) -> str:
    """把回答中残留的品牌占位符替换为真实商户名,杜绝跨租户品牌泄漏。"""
    if not raw_content:
        return ""
    brand_name = get_merchant_display_name(tenant_id)
    is_specific_merchant = tenant_id in ("adidas", "nike")

    def _replace(match: re.Match[str]) -> str:
        captured = match.group(1)
        lower = captured.lower()
        if lower in ("ecommerce", "brand", "store", "merchant", "shop", tenant_id):
            return brand_name
        if lower in ("adidas", "nike"):
            return get_merchant_display_name(lower)
        return match.group(0)

    sanitized = _PLACEHOLDER_RE.sub(_replace, raw_content)

    if is_specific_merchant:
        for token in ("ECOMMERCE", "BRAND", "STORE", "MERCHANT", "SHOP"):
            sanitized = re.sub(rf"\[{token}\]", brand_name, sanitized, flags=re.IGNORECASE)
        sanitized = sanitized.replace("官方综合商城", brand_name)
    else:
        sanitized = re.sub(r"\[ECOMMERCE\]", "官方综合商城", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r"\[BRAND\]", "官方综合商城", sanitized, flags=re.IGNORECASE)

    return sanitized
