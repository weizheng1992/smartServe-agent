"""promptfoo 自定义 Provider(Python)— 直连 .env 配置的 OpenAI 兼容端点。

供 planner / classify 提示词回归分册使用(主套件走 agent_provider.py)。
模型/端点/密钥一律取 AI_MODEL / AI_BASE_URL / AI_API_KEY(promptfoo 启动时
经 dotenv 注入进程环境),不落回任何硬编码地址——旧 127.0.0.1:11211 本地
网关已下线,静默回落缺省地址只会产出难排查的 ECONNREFUSED(见 CHANGELOG)。
"""

from __future__ import annotations

import json
import os
import urllib.request

_TIMEOUT_SECONDS = 60


def call_api(prompt, options=None, context=None):  # promptfoo provider 接口约定
    model = os.environ.get("AI_MODEL")
    base_url = os.environ.get("AI_BASE_URL")
    api_key = os.environ.get("AI_API_KEY")
    if not (model and base_url and api_key):
        return {"error": "AI_MODEL / AI_BASE_URL / AI_API_KEY missing from environment (check repo .env)"}

    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
    ).encode("utf-8")
    # 端点来自仓库 .env,非用户输入
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read())
    except Exception as err:  # noqa: BLE001 — provider 边界,错误需透传给 promptfoo 展示
        return {"error": f"LLM call failed: {type(err).__name__}: {err}"}

    content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
    if content is None:
        return {"error": f"Unexpected API response shape: {json.dumps(data, ensure_ascii=False)[:300]}"}
    return {"output": content}
