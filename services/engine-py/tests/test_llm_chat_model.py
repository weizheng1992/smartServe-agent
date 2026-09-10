"""Chat 模型工厂 payload 卫生 — bigmodel 参数兼容收口(2026-09-09)。

langchain-openai 1.6.0 的 with_structured_output(method="function_calling")
固定发送 OpenAI 专有参数 ``parallel_tool_calls: false``、``stream: false`` 与
对象形式 ``tool_choice``;bigmodel glm-4.7 对 parallel_tool_calls 任意组合、
stream:false 与 tools 同现、tool_choice 对象形式({"type":"function",...} 及
{"type":"auto"})均回 HTTP 400 code 1210(glm-4.6v 均收,vision 通路因此幸免),
导致 triage 分类器/商品归属消歧等全部结构化调用失败,并被关键词兜底静默掩盖。
``_ResilientChatOpenAI._get_request_payload`` 统一剥离前两者、把 tool_choice
对象改写为字符串 "required"(实测直接剥除时模型遇闲聊 prompt 不调工具,结构化
解析即失败;"required" 强制调用语义等价且 bigmodel 收)—— 本套钉死该契约:
- 直传 kwargs 剥离/改写;
- with_structured_output 全链路(echo 服务器抓真实请求体)生效且解析不受影响。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from engine_py.llm import chat as chatmod
from engine_py.llm.chat import get_chat_model


class TestBigmodelParamStripped:
    def test_direct_kwargs_stripped_from_payload(self):
        payload = get_chat_model()._get_request_payload(
            "hi",
            parallel_tool_calls=False,
            stream=False,
            tool_choice={"type": "function", "function": {"name": "T"}},
        )
        assert "parallel_tool_calls" not in payload
        # stream:false 仅与 tools 同现才剥(2026-09-10 修正):本直传无 tools,
        # 键保留 —— SDK response_format 路径的 ``payload.pop("stream")`` 依赖键存在,
        # 无条件剥除曾令默认 method 结构化调用全量 KeyError('stream')
        assert payload.get("stream") is False
        assert payload["tool_choice"] == "required"  # 对象形式改写,非剥除(闲聊 prompt 下仍强制调工具)

    def test_structured_output_request_omits_param_end_to_end(self):
        """echo 服务器抓 with_structured_output 实际发出的请求体(不触外网)。"""
        captured: dict = {}

        class _Echo(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                captured["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                # 回显请求声明的函数名(with_structured_output 以 pydantic 类名命名)
                fn_name = captured["body"]["tools"][0]["function"]["name"]
                resp = json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "tool_calls",
                                "index": 0,
                                "message": {
                                    "content": "",
                                    "role": "assistant",
                                    "tool_calls": [
                                        {
                                            "function": {"arguments": '{"ok": true}', "name": fn_name},
                                            "id": "call_test",
                                            "index": 0,
                                            "type": "function",
                                        }
                                    ],
                                },
                            }
                        ],
                        "created": 1,
                        "id": "x",
                        "model": "echo",
                        "object": "chat.completion",
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *args) -> None:  # 静默访问日志
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)  # 0 = 随机空闲端口
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            # settings 为 frozen dataclass,且工厂 lru_cache 单例读模块级引用:
            # 换模块级 settings 指针 + 清缓存,测试后还原并再清,防污染其他用例
            fake = SimpleNamespace(
                llm_base_url=f"http://127.0.0.1:{server.server_port}/v1",
                llm_api_key="sk-test",
                llm_model="glm-4.7",
                llm_thinking="disabled",
            )
            original_settings = chatmod.settings
            chatmod.settings = fake  # type: ignore[assignment]
            chatmod.get_chat_model.cache_clear()
            model = chatmod.get_chat_model()
            try:
                from pydantic import BaseModel

                class _T(BaseModel):
                    ok: bool

                structured = model.with_structured_output(_T, method="function_calling")
                result = structured.invoke("返回 ok=true")
                assert result.ok is True  # 解析链路不受剥离影响
                assert "parallel_tool_calls" not in captured["body"]
                assert captured["body"].get("stream") is not False  # stream:false + tools 同现即 1210
                assert captured["body"]["tool_choice"] == "required"  # 对象形式 1210,改写非剥除
                assert "tools" in captured["body"]  # 工具本体仍在(只剥兼容参数)
                # 思维链关闭同点注入:thinking 与 tools 同现 bigmodel 收(实测),且必须
                # 穿透 with_structured_output —— 否则 triage 分类器仍带 reasoning 拖延迟
                assert captured["body"]["thinking"] == {"type": "disabled"}
            finally:
                chatmod.settings = original_settings  # type: ignore[assignment]
                chatmod.get_chat_model.cache_clear()
        finally:
            server.shutdown()
            server.server_close()

    def test_structured_output_default_method_not_broken_by_stream_strip(self):
        """默认 method(response_format/json_schema 路径)回归钉死(2026-09-10):

        SDK ``_agenerate`` 对 response_format 载荷执行无守卫 ``payload.pop("stream")``,
        依赖 stream 键存在;1b15979 的无条件剥除令该路径全量 KeyError('stream'),
        结构化调用被静默打落到 prompt 兜底(3 次退避重试 + 一次兜底调用,延迟与
        成本双涨)。本用例证明默认 method 的结构化调用在剥除逻辑下仍然存活。
        """
        captured: dict = {}

        class _EchoJson(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                captured["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                resp = json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "index": 0,
                                "message": {"content": '{"ok": true}', "role": "assistant"},
                            }
                        ],
                        "created": 1,
                        "id": "x",
                        "model": "echo",
                        "object": "chat.completion",
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *args) -> None:  # 静默访问日志
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoJson)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            fake = SimpleNamespace(
                llm_base_url=f"http://127.0.0.1:{server.server_port}/v1",
                llm_api_key="sk-test",
                llm_model="glm-4.7",
                llm_thinking="disabled",
            )
            original_settings = chatmod.settings
            chatmod.settings = fake  # type: ignore[assignment]
            chatmod.get_chat_model.cache_clear()
            model = chatmod.get_chat_model()
            try:
                from pydantic import BaseModel

                class _T(BaseModel):
                    ok: bool

                structured = model.with_structured_output(_T)  # 默认 method
                result = structured.invoke("返回 ok=true")
                assert result.ok is True  # 此前该调用 KeyError('stream') 三连后落兜底
                assert "response_format" in captured["body"]  # 确认走的是 response_format 路径
            finally:
                chatmod.settings = original_settings  # type: ignore[assignment]
                chatmod.get_chat_model.cache_clear()
        finally:
            server.shutdown()
            server.server_close()


class TestThinkingDisabled:
    """思维链关闭注入(2026-09-09):glm-4.7 默认 thinking 使琐碎调用也生成大量
    reasoning token(客服管线 3 次串行调用即 1-2 分钟回复)。默认 disabled 注入;
    AI_THINKING=enabled 不注入;调用方显式 thinking 覆写不被踩。"""

    def test_disabled_injected_by_default(self):
        payload = get_chat_model()._get_request_payload("hi")
        assert payload["extra_body"]["thinking"] == {"type": "disabled"}

    def test_explicit_caller_override_respected(self):
        payload = get_chat_model()._get_request_payload(
            "hi", extra_body={"thinking": {"type": "enabled"}}
        )
        assert payload["extra_body"]["thinking"] == {"type": "enabled"}  # setdefault 语义,不踩显式覆写

    def test_enabled_setting_skips_injection(self):
        original_settings = chatmod.settings
        chatmod.settings = SimpleNamespace(
            llm_base_url="http://127.0.0.1:9/v1",
            llm_api_key="sk-test",
            llm_model="glm-4.7",
            llm_thinking="enabled",
        )
        chatmod.get_chat_model.cache_clear()
        try:
            payload = chatmod.get_chat_model()._get_request_payload("hi")
            assert "thinking" not in (payload.get("extra_body") or {})
        finally:
            chatmod.settings = original_settings  # type: ignore[assignment]
            chatmod.get_chat_model.cache_clear()


if __name__ == "__main__":
    pytest.main([__file__])
