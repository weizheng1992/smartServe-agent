"""视觉定损真弹冒烟(手动工具,非 pytest —— 真弹结果严禁写成测试断言)。

直调 ``engine_py.vision.analyze_images`` 打真视觉模型(默认 glm-4.6v),回答
「模型现在怎么判断物品坏了」:评级等级/置信度、OCR 单号、trust rules 是否
无视图内嵌字、evidenceChannel 来源标记。契约层回归在
``services/engine-py/tests/test_vision_analyzer.py``(回放实弹采集的模型输出
dict,零联网);两者职责不同,严禁把本工具的输出固化成断言 —— 模型措辞
每晚漂移,真弹回归资产走 ``vision_audit_agg`` 聚合与坏例池(2026-10-17 视觉加固)。

用法(在 services/engine-py 下跑,复用其 uv 环境):

    set -a; source ../../.env; set +a   # AI_BASE_URL / AI_API_KEY
    uv run python ../../scripts/vision/smoke.py \\
        /api/uploads/<file.png> "鞋坏了,要退货" \\
        /api/uploads/<other.jpg> "看看买的衣服"

图片引用支持三种形态:``/api/uploads/<file>``(网关落盘约定)/裸文件名(自动
补前缀,落仓库根 ``public/uploads``)/http(s) 公网 URL(原样透传)。不带参数
时跑内置三组对照(破损×称坏 / 完好×中性 / 完好×谎称坏;图缺失自动跳过)。

对照解读口径(2026-10-17 实测基线):完好图 × 谎称坏了 → 模型应判 negligible
并在 summary 明说「用户声称坏了但图中无损坏迹象」—— 评级以图像像素证据为准,
用户话术只是上下文;这正是「如何判断物品坏了」的核心行为。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_UPLOADS = "public/uploads"

# 内置三组对照(图源自 2026-09-09 E2E 事故期真实上传,缺失时自动跳过)
_DEFAULT_CASES = [
    ("33b1cc697f3941818f43480e0c0299f5.png", "鞋坏了,开胶断裂,要退货退款", "A 破损图×称坏了"),
    ("3a50ce392583486a810da678a513f58e.jpg", "看看我买的裤子", "B 完好裤×中性"),
    ("8fcebdc030c748cfad614b3fcd82916e.jpg", "这衣服坏了,要求退款", "C 完好夹克×谎称坏了"),
]


def _load_dotenv_if_missing() -> None:
    """仓库根 .env → os.environ(仅补缺,显式 env 优先;config 在导入时读 env)。"""
    env_path = _ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _normalize_image_ref(ref: str) -> str:
    """裸文件名 → /api/uploads/<file>(analyzer 只认该前缀为本地落盘图)。"""
    if ref.startswith(("http://", "https://", "/api/uploads/")):
        return ref
    return f"/api/uploads/{ref}"


def _resolve_uploads(name: str) -> Path:
    return Path(os.environ.get("UPLOADS_DIR") or (_ROOT / _UPLOADS)) / name


def _print_result(label: str, image: str, prompt: str, res: dict) -> None:
    dmg = res.get("damageAssessment")
    print("=" * 70)
    print(f"[{label}] {image} | 用户文本: {prompt!r}")
    print(
        json.dumps(
            {
                "visualSummary": res.get("visualSummary"),
                "detectedObjects": res.get("detectedObjects"),
                "extractedOrderId": res.get("extractedOrderId"),
                "ocrTextHead": (res.get("ocrText") or "")[:60],
                "damageAssessment": dmg,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


async def _run(pairs: list[tuple[str, str, str]]) -> None:
    from engine_py.vision import analyze_images  # env 就绪后再导入(config 导入时读 env)

    for image, prompt, label in pairs:
        res = await analyze_images([_normalize_image_ref(image)], prompt)
        _print_result(label, image, prompt, res)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="视觉定损真弹冒烟(手动工具;真弹结果严禁写成测试断言)",
    )
    parser.add_argument(
        "cases",
        nargs="*",
        help="成对传入:图片引用 用户文本(可多组;缺省跑内置三组对照)",
    )
    args = parser.parse_args()

    if args.cases:
        if len(args.cases) % 2:
            parser.error("须成对传入:图片引用 用户文本")
        pairs = [
            (img, prompt, f"自定义 {i}")
            for i, (img, prompt) in enumerate(zip(args.cases[::2], args.cases[1::2]), 1)
        ]
    else:
        pairs = [
            (img, prompt, label)
            for img, prompt, label in _DEFAULT_CASES
            if _resolve_uploads(Path(img).name).is_file()
        ]
        missing = [img for img, _, _ in _DEFAULT_CASES if not _resolve_uploads(Path(img).name).is_file()]
        if missing:
            print(f"[smoke] 跳过不存在的默认对照图: {missing}")
    if not pairs:
        parser.error("无可用用例(默认图缺失且未传参)")

    _load_dotenv_if_missing()
    if not os.environ.get("AI_BASE_URL") or not os.environ.get("AI_API_KEY"):
        parser.error("AI_BASE_URL / AI_API_KEY 未配置(仓库根 .env 或环境变量)")

    asyncio.run(_run(pairs))


if __name__ == "__main__":
    main()
