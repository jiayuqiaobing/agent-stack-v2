import base64

from runtime.ingest import can_see_images, has_image, prepare_attachments


def test_non_vision_model_cannot_see_images():
    assert can_see_images("gpt-4o-mini")
    assert not can_see_images("cheapai/grok-4.7")
    assert has_image([{"mime": "image/png"}])
    assert not has_image([{"mime": "text/plain"}])


def test_empty_and_oversize_files_are_rejected():
    empty = prepare_attachments([{"name": "empty.txt", "mime": "text/plain", "data_base64": ""}])
    assert "空文件" in empty["text"]
    raw = base64.b64encode(b"a" * (8_000_001)).decode()
    huge = prepare_attachments([{"name": "big.txt", "mime": "text/plain", "data_base64": raw}])
    assert "8MB" in huge["text"]
    assert prepare_attachments(None) == {"text": "", "images": []}


def test_bad_base64_is_reported_not_dropped():
    result = prepare_attachments([{"name": "a.txt", "mime": "text/plain", "data_base64": "%%%"}])
    assert "a.txt" in result["text"]
    assert "base64" in result["text"]
    assert result["images"] == []


def test_only_six_attachments_are_processed():
    items = [
        {"name": f"{i}.txt", "mime": "text/plain", "data_base64": "%%%"}
        for i in range(8)
    ]
    result = prepare_attachments(items)
    assert result["text"].count("[附件") == 6


def test_text_attachment_is_not_silent():
    raw = base64.b64encode("hello-attachment".encode()).decode()
    result = prepare_attachments([{"name": "note.txt", "mime": "text/plain", "data_base64": raw}])
    assert "note.txt" in result["text"]
    assert result["text"].strip() != ""


def test_image_is_separated_from_text():
    raw = base64.b64encode(b"png").decode()
    result = prepare_attachments([{"name": "a.png", "mime": "image/png", "data_base64": raw}])
    assert result["images"]
    assert result["images"][0].startswith("data:image/png;base64,")
