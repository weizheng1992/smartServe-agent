"""视觉解析模块 — 移植 TS vision/visionAnalyzerService.ts(wayfinder multimodal-image-chat 003)。

考古基准:commit f71f7fa,树 b75fb78^。继承:OCR 单号正则、破损三级定责、
启发式正则兜底(纯函数)、PII 脱敏切面、prompt 任务定义。改良 TS 缺陷:

- 手写 ```json 围栏剥离 → Pydantic 结构化输出,method="function_calling"
  (001 裁决:GLM-4.6V 无 response_format,仅 tools 白名单可取参)。
- 1500ms Promise.race 硬超时(真实多模态必降级)→ 模型级 request_timeout,
  ``AI_VISION_TIMEOUT_SECONDS`` 可调(默认 15s);失败保留启发式部分结果。
- TS 传公网 CDN URL;本地图(``/api/uploads/``)经 base64 Data URL 直传 ——
  bigmodel 拉不到 localhost,同时免本地文件服务出网暴露。

出参字典 camelCase(镜像 TS VisionAnalysisResult);``damageAssessment`` 字段名
冻结(``packages/types/src/card.ts`` DamageAssessmentData + 前端卡片在用)。
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from ..llm import get_vision_model
from ..tools_registry.scrubber import scrub_pii_string
from ..triage.intent_registry import VISION_ORDER_ID_RE  # 图内 OCR 单号正则收口 intent_registry(工单04)

# ---- TS 原版正则,1:1 继承(破损词表按真实措辞扩充,见 docstring) ----
_ORDER_RE = VISION_ORDER_ID_RE
_TRACKING_RE = re.compile(r"\b(SF|YTO|ZTO|EMS|TRACK)[\w\d]{8,14}\b", re.IGNORECASE)
# 破损词表:TS 原版 + 开胶/断裂/脱胶(E2E 实测「鞋底开胶断裂」全不命中,
# LLM 超时降级后连兜底定责都丢——类目真实措辞,补词非契约变更)
_DAMAGE_RE = re.compile(
    r"破损|坏了|碎了|裂开|断裂|开胶|脱胶|漏液|划痕|撕裂|瑕疵|damage|broken|crack|stain|defect",
    re.IGNORECASE,
)
_DAMAGE_SEVERE_RE = re.compile(r"严重|彻底|全碎|碎裂|severe|crushed", re.IGNORECASE)

_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_UPLOAD_URL_PREFIX = "/api/uploads/"

# 引擎侧入图总量护栏(wayfinder multimodal 005):数量上限与网关单张限额
# (10MB/张,上传端点钳制)对齐 —— 引擎不重复拉网络图,只透传/转 Data URL,
# 数量截断即总量上限;GLM-4.6V 官方上限 50 图/请求,3 图远在射程内。
MAX_IMAGES_PER_MESSAGE = 3


def normalize_image_urls(image_urls: list[str] | None, *, max_images: int = MAX_IMAGES_PER_MESSAGE) -> list[str]:
    """入图归一化与限额(TS 时代零防护,wayfinder multimodal 005 治理)。

    剔除非字符串/空白项、去重保序、截断至 ``max_images``;垃圾输入最多变少图,
    绝不抛错 —— 坏图限额治理的目标是"少看图",不是"失败会话"。
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for url in image_urls or []:
        if not isinstance(url, str):
            continue
        trimmed = url.strip()
        if not trimmed or trimmed in seen:
            continue
        seen.add(trimmed)
        cleaned.append(trimmed)
        if len(cleaned) >= max_images:
            break
    return cleaned


class DamageAssessment(BaseModel):
    """定责结构化输出 schema(工具取参用 snake 字段,出参转 camel 契约字典)。"""

    damage_level: Literal["negligible", "minor", "severe"] = "minor"
    summary: str = "商品外观检测"
    confidence: float = 0.85
    suggested_action: Literal["auto_refund", "require_inspection", "human_review"] = "human_review"


class VisionAnalysis(BaseModel):
    """多模态视觉精判的完整结构(LLM 成功分支的取参目标)。"""

    visual_summary: str = ""
    detected_objects: list[str] = Field(default_factory=list)
    extracted_order_id: str | None = None
    extracted_tracking_number: str | None = None
    ocr_text: str | None = None
    damage_assessment: DamageAssessment | None = None


def _uploads_dir() -> Path:
    """本地图目录:与 gateway-py 同约定(``UPLOADS_DIR`` env 或仓库根 public/uploads)。

    每次调用时读 env 而非 Settings 快照 —— Settings 是 frozen dataclass,
    测试以 monkeypatch.setenv 注入临时目录须即时生效。
    """
    env = os.environ.get("UPLOADS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[5] / "public" / "uploads"


def _to_llm_image_url(url: str) -> str | None:
    """图片引用 → 模型可读 URL。

    ``/api/uploads/<file>``(单实例本地存储)→ base64 Data URL;文件缺失或后缀
    不识别返回 None(该图跳过,不炸整体)。绝对 http(s) URL 原样透传(公网图)。
    """
    if not url.startswith(_UPLOAD_URL_PREFIX):
        return url
    path = _uploads_dir() / url[len(_UPLOAD_URL_PREFIX) :]
    mime = _MIME_BY_EXT.get(path.suffix.lower())
    if not mime or not path.is_file():
        return None
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _heuristic_damage_assessment(raw_text: str, primary_url: str) -> dict | None:
    """启发式破损定责(TS 统一助手 1:1):关键词命中才产出,confidence 0.88。"""
    if not _DAMAGE_RE.search(raw_text):
        return None
    is_severe = bool(_DAMAGE_SEVERE_RE.search(raw_text))
    return {
        "damageLevel": "severe" if is_severe else "minor",
        "summary": "用户上传了商品严重破损/碎裂照片" if is_severe else "用户上传了商品瑕疵/局部破损凭证照片",
        "confidence": 0.88,
        "suggestedAction": "auto_refund" if is_severe else "human_review",
        "imageUrl": primary_url,
    }


_PROMPT_TEMPLATE = """You are an expert AI Vision and OCR inspection assistant for an e-commerce customer support platform.
Analyze the provided image(s) and user message.
User Message: "{user_prompt}"

Your tasks:
1. OCR: Extract any visible Order IDs (e.g. "ORD-12345"), Tracking/Airway Bill Numbers (e.g. "SF1234567890"), and general text.
2. Defect & Damage Inspection: Determine if the product has damage or defects.
   - damageLevel: "negligible" (minor scratch/normal wear), "minor" (small defect/stain), or "severe" (shattered/crushed/completely unusable).
   - summary: Brief Chinese description of the damage or visual content.
   - suggestedAction: "auto_refund" | "require_inspection" | "human_review".
3. Return: visualSummary (string), detectedObjects (string[]), extractedOrderId, extractedTrackingNumber, ocrText, damageAssessment (null if no damage)."""


def _fallback_result(order_id: str | None, tracking_no: str | None, raw_text: str, primary_url: str) -> dict:
    """降级兜底(TS catch 分支 1:1):启发式定责 + 正则提取的单号。"""
    return {
        "visualSummary": "已接收并解析用户上传的商品与物流凭证图片",
        "detectedObjects": ["product_image", "receipt"],
        "extractedOrderId": order_id,
        "extractedTrackingNumber": tracking_no,
        "ocrText": order_id or tracking_no or "",
        "damageAssessment": _heuristic_damage_assessment(raw_text, primary_url),
    }


async def analyze_images(image_urls: list[str], user_prompt: str = "", *, model=None) -> dict:
    """视觉与多模态核心解析:OCR 面单实体、破损定责、视觉摘要。

    任何模型侧异常(超时/网络/结构化解析失败)降级启发式 —— vision 失败
    绝不炸会话主链路;单图不可读跳过该图,全部不可读时直接走启发式。
    """
    empty = {
        "visualSummary": "",
        "detectedObjects": [],
        "extractedOrderId": None,
        "extractedTrackingNumber": None,
        "ocrText": None,
        "damageAssessment": None,
    }
    if not image_urls:
        return empty

    primary_url = image_urls[0]
    raw_text = f"{user_prompt} {' '.join(image_urls)}"
    order_match = _ORDER_RE.search(raw_text)
    tracking_match = _TRACKING_RE.search(raw_text)
    order_id = order_match.group(0).upper() if order_match else None
    tracking_no = tracking_match.group(0).upper() if tracking_match else None

    llm_urls = []
    for url in image_urls:
        resolved = _to_llm_image_url(url)
        if resolved:
            llm_urls.append(resolved)
        else:
            print(f"[Vision] 图片不可读,已跳过: {url}")

    if not llm_urls:
        return _fallback_result(order_id, tracking_no, raw_text, primary_url)

    try:
        chat = model or get_vision_model()
        structured = chat.with_structured_output(VisionAnalysis, method="function_calling")
        content: list[dict] = [
            {"type": "text", "text": _PROMPT_TEMPLATE.format(user_prompt=user_prompt)}
        ]
        content += [{"type": "image_url", "image_url": {"url": u}} for u in llm_urls]
        parsed = await structured.ainvoke([HumanMessage(content=content)])

        damage = parsed.damage_assessment
        if damage is not None:
            confidence = damage.confidence
            if not isinstance(confidence, (int, float)) or not (0 < confidence <= 1):
                confidence = 0.85
            damage_dict = {
                "damageLevel": damage.damage_level or "minor",
                "summary": scrub_pii_string(damage.summary or "商品外观检测"),
                "confidence": confidence,
                "suggestedAction": damage.suggested_action or "human_review",
                "imageUrl": primary_url,  # 服务端强制回填原始引用,不采模型值
            }
        else:
            damage_dict = _heuristic_damage_assessment(raw_text, primary_url)

        return {
            "visualSummary": scrub_pii_string(parsed.visual_summary or ""),
            "detectedObjects": parsed.detected_objects or [],
            "extractedOrderId": parsed.extracted_order_id or order_id,
            "extractedTrackingNumber": parsed.extracted_tracking_number or tracking_no,
            "ocrText": scrub_pii_string(parsed.ocr_text or ""),
            "damageAssessment": damage_dict,
        }
    except Exception as vision_err:
        print(f"[VisionAnalyzer] 多模态精判失败,降级启发式: {vision_err}")
        return _fallback_result(order_id, tracking_no, raw_text, primary_url)
