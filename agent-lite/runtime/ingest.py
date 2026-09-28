"""附件兼容层。清洗交给 MarkItDown，看图交给当前模型的视觉接口。

这里不写 PDF、表格或 OCR 算法。库没装好或转失败时，只返回一句错误。
"""

import base64
import os
import tempfile

_IMAGE = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_LIMIT = 8_000_000
_VISION = ("gpt-4o", "gpt-4.1", "gpt-4-turbo", "gemini", "claude-3", "claude-4", "-vl", "qwen-vl", "glm-4v")


def can_see_images(model: str | None) -> bool:
    name = (model or "").lower()
    return any(key in name for key in _VISION)


def _convert(path: str, name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            if ext == ".pdf":
                return "错误: 未安装 Docling，PDF 未清洗"
        else:
            result = DocumentConverter().convert(path)
            return result.document.export_to_markdown() or ""
    from markitdown import MarkItDown
    return MarkItDown().convert(path).text_content or ""


def has_image(items: list | None) -> bool:
    if not isinstance(items, list):
        return False
    for item in items:
        if isinstance(item, dict) and str(item.get("mime") or "").lower().startswith("image/"):
            return True
    return False


def prepare_attachments(items: list | None) -> dict:
    texts = []
    images = []
    if not isinstance(items, list):
        return {"text": "", "images": images}
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "附件")[:120]
        mime = str(item.get("mime") or "application/octet-stream").split(";")[0].strip().lower()
        raw_b64 = str(item.get("data_base64") or "")
        try:
            raw = base64.b64decode(raw_b64, validate=True)
        except Exception:
            texts.append(f"[附件 {name}] 错误: 内容不是有效的 base64")
            continue
        if not raw:
            texts.append(f"[附件 {name}] 错误: 空文件")
            continue
        if len(raw) > _LIMIT:
            texts.append(f"[附件 {name}] 错误: 超过 8MB，未处理")
            continue
        if mime in _IMAGE:
            images.append(f"data:{mime};base64,{raw_b64}")
        suffix = os.path.splitext(name)[1][:12] or ".bin"
        path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(raw)
                path = tmp.name
            text = _convert(path, name)
        except Exception as e:
            text = f"错误: 清洗失败: {type(e).__name__}"
        finally:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        body = text.strip()[:12000] or "（没有抽出文字）"
        texts.append(f"[附件 {name}]\n{body}")
    return {"text": "\n\n".join(texts), "images": images}
