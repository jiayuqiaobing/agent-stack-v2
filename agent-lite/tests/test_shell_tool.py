import asyncio
import sys

from runtime.shell_tool import run_command


def test_empty_and_escape_are_rejected():
    assert asyncio.run(run_command("  ")).startswith("错误")
    assert asyncio.run(run_command("rm -rf /")).startswith("错误")
    assert asyncio.run(run_command("cd ..")).startswith("错误")


def test_allowed_command_returns_output():
    result = asyncio.run(run_command(f'"{sys.executable}" -c "print(42)"'))
    assert "42" in result
    assert not result.startswith("错误")
