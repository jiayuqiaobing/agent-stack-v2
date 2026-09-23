"""
test08/mcp_server.py

MCP 协议服务端 — 暴露工具给外部 Agent 调用
运行方式：python mcp_server.py（独立进程，stdio 传输）
"""

import logging
import requests
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ============================================================================
# MCP 实例初始化
# ============================================================================

mcp = FastMCP("test08_agent_tools")


# ============================================================================
# MCP 工具定义
# ============================================================================


@mcp.tool()
def get_weather(city: str, day: str = "today") -> str:
    """
    查询指定城市的天气信息，可查今天/明天/后天。

    参数：
        city: 城市名称，如"北京"、"上海"、"Tokyo"
        day: today（今天）/ tomorrow（明天）/ the_day_after_tomorrow（后天）/ all（三天）
    返回：天气描述 + 温度范围
    """
    try:
        url = f"https://wttr.in/{city}?format=j1"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        weather = data["weather"]
        day_map = {"today": 0, "tomorrow": 1, "the_day_after_tomorrow": 2}

        if day == "all":
            return "\n\n".join(_format_day(d) for d in weather)

        idx = day_map.get(day, 0)
        return _format_day(weather[idx])

    except requests.RequestException as e:
        logger.warning("天气 API 请求失败：%s", e)
        return f"天气查询失败（网络错误）：{e}"
    except (KeyError, IndexError) as e:
        logger.warning("天气数据解析失败：%s", e)
        return f"天气数据解析失败：{e}"


def _format_day(d: dict) -> str:
    """格式化单天天气"""
    date = d["date"]
    high = d["maxtempC"]
    low = d["mintempC"]
    desc = d["hourly"][4]["weatherDesc"][0]["value"]
    return f"{date}：{desc}，{low}°C ~ {high}°C"



# ============================================================================
# 启动 MCP Server
# ============================================================================

if __name__ == "__main__":
    print("🚀 test08 MCP Server 启动（stdio 模式）")
    mcp.run(transport="stdio")
