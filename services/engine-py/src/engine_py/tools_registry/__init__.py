"""工具注册表 — 镜像 tools/src/registry.ts(注册即包裹 PII 脱敏层)。

导入本包即完成 19 个电商工具的注册(等价 TS 的模块求值期 registerTool 副作用)。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .scrubber import scrub_pii

ToolExecute = Callable[[dict], Awaitable[Any]]


class ToolDefinition:
    def __init__(self, name: str, description: str, schema: dict | None, execute: ToolExecute) -> None:
        self.name = name
        self.description = description
        self.schema = schema or {}
        self._execute = execute

    async def execute(self, args: dict) -> Any:
        scrubbed_args = scrub_pii(args)
        result = await self._execute(scrubbed_args)
        return scrub_pii(result)


_registry: dict[str, ToolDefinition] = {}


def register_tool(tool: ToolDefinition) -> None:
    _registry[tool.name] = tool


def get_tool(name: str) -> ToolDefinition | None:
    return _registry.get(name)


def get_all_tools() -> list[ToolDefinition]:
    return list(_registry.values())


# 导入即注册(镜像 TS 的模块顶层 registerTool 调用)
from . import ecommerce_tools as _ecommerce_tools  # noqa: F401
