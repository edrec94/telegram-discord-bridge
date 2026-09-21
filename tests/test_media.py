from types import SimpleNamespace

from media import RecentMessageIds, build_source_link, is_downloadable_size, pick_caption


def _msg(id_=1, text="", size=None):
    file_obj = SimpleNamespace(size=size) if size is not None else None
    return SimpleNamespace(id=id_, message=text, file=file_obj)


def test_build_source_link_public_channel():
    link = build_source_link("mychannel", 123, 456)
    assert link == "https://t.me/mychannel/456"


def test_build_source_link_private_channel_strips_100_prefix():
    link = build_source_link(None, -1001234567890, 42)
    assert link == "https://t.me/c/1234567890/42"


def test_pick_caption_returns_first_non_empty():
    messages = [_msg(1, ""), _msg(2, "the caption"), _msg(3, "ignored second caption")]
    assert pick_caption(messages) == "the caption"


def test_pick_caption_empty_when_no_text():
    messages = [_msg(1, ""), _msg(2, "")]
    assert pick_caption(messages) == ""


def test_is_downloadable_size_within_limit():
    msg = _msg(1, size=1024)
    assert is_downloadable_size(msg, max_bytes=2048) is True


def test_is_downloadable_size_over_limit():
    msg = _msg(1, size=10_000_000)
    assert is_downloadable_size(msg, max_bytes=1_000_000) is False


def test_is_downloadable_size_no_file_info_defaults_true():
    msg = _msg(1, size=None)
    assert is_downloadable_size(msg, max_bytes=1024) is True


def test_recent_message_ids_dedup():
    recent = RecentMessageIds(maxlen=10)
    assert recent.seen_or_add(1) is False
    assert recent.seen_or_add(1) is True
    assert recent.seen_or_add(2) is False


def test_recent_message_ids_bounded_eviction():
    recent = RecentMessageIds(maxlen=2)
    assert recent.seen_or_add(1) is False
    assert recent.seen_or_add(2) is False
    assert recent.seen_or_add(3) is False  # evicts 1
    assert recent.seen_or_add(1) is False  # 1 was evicted, treated as new
    assert recent.seen_or_add(3) is True   # 3 still tracked
