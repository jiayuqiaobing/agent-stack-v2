"""这一轮选中的工具：名字、说明、参数、执行。"""

import json

from runtime.assist import run_assist
from tools_local import TOOL_REGISTRY, execute_tool


class ToolRegistry:
    def __init__(self, schemas: list | None = None, tool_session_map: dict | None = None, mcp_call=None):
        self.schemas = list(schemas or [])
        self.tool_session_map = tool_session_map or {}
        self.mcp_call = mcp_call
        self.cache: dict[str, str] = {}
        self.by_name = {}
        for item in self.schemas:
            if not isinstance(item, dict):
                continue
            fn = item.get("function") or {}
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            if name:
                self.by_name[name] = {
                    "name": name,
                    "description": fn.get("description") or "",
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                    "source": "local" if name in TOOL_REGISTRY or name == "web_search" else "mcp",
                }

    def exposed(self) -> list:
        unique = []
        names = set()
        for item in self.schemas:
            fn = item.get("function") if isinstance(item, dict) else None
            name = fn.get("name") if isinstance(fn, dict) else None
            if name and name not in names:
                names.add(name)
                unique.append(item)
        return unique

    def source_of(self, name: str) -> str:
        spec = self.by_name.get(name)
        if spec:
            return spec["source"]
        if name in TOOL_REGISTRY:
            return "local"
        if name in self.tool_session_map:
            return "mcp"
        return "unknown"

    async def call(self, name: str, args: dict) -> str:
        try:
            cache_key = name + ":" + json.dumps(args or {}, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            cache_key = ""
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]
        handled = await run_assist(name, args)
        if handled is not None:
            result = handled
            if cache_key:
                self.cache[cache_key] = result
            return result
        if name in TOOL_REGISTRY:
            result = await execute_tool(name, args)
            if cache_key:
                self.cache[cache_key] = result
            return result
        info = self.tool_session_map.get(name)
        if info and self.mcp_call:
            result = await self.mcp_call(info, name, args)
            if cache_key:
                self.cache[cache_key] = result
            return result
        return f"错误: 未知工具 '{name}'"
