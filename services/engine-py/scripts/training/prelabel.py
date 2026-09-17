"""LLM 预标(可选,11-D3 流水线第 3 步):对水龙头导出的未标注句给第二意见。

分工:export 出的 intent 字段即「管线意见」(第一意见);本脚本调 LLM 给第二意见;
两意见不一致或 LLM 低置信 → need_review=true(人工只裁这部分,06 号实测可将标注
成本降一个量级)。直连 OpenAI 兼容 /chat/completions,不耦合 engine 运行时——
参数取 --base-url/--model/--api-key,缺省回落 AI_BASE_URL / AI_MODEL / AI_API_KEY
/ OPENAI_API_KEY 环境变量。

用法::

    uv run python scripts/training/prelabel.py --config configs/metric_head.toml \
        --in /tmp/intent.jsonl --out /tmp/prelabeled.jsonl [--limit 200] [--sleep 0.2]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from common import load_config, load_jsonl, write_jsonl

PROMPT = """你是电商客服/数据问答的标注员。把用户问句归入且仅归入下列闭集标签之一:

{labels}

只输出 JSON:{{"label": "<闭集内的标签>", "confidence": <0-1 的数字>}}
无法判断或都不合适时输出闭集外的 "unsupported"。

用户问句:{query}"""


def ask_llm(client: httpx.Client, base_url: str, model: str, api_key: str, query: str, labels: list[str]) -> dict:
    resp = client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        json={
            "model": model,
            "messages": [{"role": "user", "content": PROMPT.format(labels="\n".join(f"- {x}" for x in labels), query=query)}],
            "temperature": 0,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    try:
        parsed = json.loads(content[content.index("{") : content.rindex("}") + 1])
        return {"label": str(parsed.get("label")), "confidence": float(parsed.get("confidence", 0.0))}
    except (ValueError, KeyError):
        return {"label": "unsupported", "confidence": 0.0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM 预标:给导出句打第二意见,标记人工复核项")
    parser.add_argument("--config", required=True)
    parser.add_argument("--in", dest="in_jsonl", required=True, help="export_intent_data.py 的导出 JSONL")
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, help="最多处理 N 条(先小批试跑)")
    parser.add_argument("--sleep", type=float, default=0.2, help="请求间隔秒数(限速)")
    parser.add_argument("--base-url", default=os.environ.get("AI_BASE_URL", "http://127.0.0.1:11211/api/openai/v1"))
    parser.add_argument("--model", default=os.environ.get("AI_MODEL", "gemini-3.5-flash:latest"))
    parser.add_argument("--api-key", default=os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY", ""))
    args = parser.parse_args(argv)

    labels: list[str] = load_config(args.config)["task"]["labels"]
    records = [r for r in load_jsonl(args.in_jsonl) if r.get("query")]
    if args.limit:
        records = records[: args.limit]

    out, n_review = [], 0
    with httpx.Client() as client:
        for i, r in enumerate(records):
            try:
                llm = ask_llm(client, args.base_url, args.model, args.api_key, r["query"], labels)
            except httpx.HTTPError as err:
                print(f"[Prelabel] 第 {i + 1} 条请求失败({err}),跳过", file=sys.stderr)
                continue
            pipeline_label = r.get("intent")
            need_review = llm["label"] != pipeline_label or llm["confidence"] < 0.7
            n_review += int(need_review)
            out.append({**r, "label": pipeline_label or llm["label"], "label_pipeline": pipeline_label,
                        "label_llm": llm["label"], "llm_confidence": llm["confidence"], "need_review": need_review})
            if args.sleep:
                time.sleep(args.sleep)

    write_jsonl(out, args.out)
    print(f"[Prelabel] {len(out)} 条 → {args.out};需人工复核 {n_review} 条(need_review=true)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
