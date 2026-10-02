from runtime.session_lookup import bind_memory, search_session_sync


def test_lookup_stays_inside_the_bound_session():
    assert search_session_sync("你好").startswith("错误")

    class Memory:
        short_term = [
            {"role": "user", "content": "怎么写一本科幻小说"},
            {"role": "tool", "content": "怎么写一本科幻小说"},
            {"role": "assistant", "content": "先查成熟写法"},
        ]

    bind_memory(Memory())
    found = search_session_sync("科幻小说")
    assert "user: 怎么写一本科幻小说" in found
    assert "tool:" not in found
    assert search_session_sync("记账") == "本会话里没有这句"
