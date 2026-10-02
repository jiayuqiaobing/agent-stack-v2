import asyncio

from runtime.browser_tool import open_page


def test_non_http_url_is_rejected_without_opening():
    result = asyncio.run(open_page("ftp://example.com"))
    assert result.startswith("错误")
    assert "http" in result
    assert asyncio.run(open_page("")).startswith("错误")
