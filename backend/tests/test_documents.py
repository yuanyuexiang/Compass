import fitz

from app.parsing.documents import parse_attachment, pdf_to_text


def make_pdf(text: str = "") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    return doc.tobytes()


def test_pdf_with_text_layer():
    data = make_pdf("Purchase budget: 3,300,000 CNY. Deadline 2026-07-09.")
    text, needs_ocr = pdf_to_text(data)
    assert "3,300,000" in text
    assert "[第1页]" in text
    assert needs_ocr is False


def test_scanned_pdf_flagged_for_ocr():
    text, needs_ocr = pdf_to_text(make_pdf())  # 无文本层 → 疑似扫描件
    assert needs_ocr is True


def test_parse_attachment_dispatch():
    body = "Tender notice content. " * 5  # 需超过扫描件判定阈值（30 字符/页）
    text, needs_ocr = parse_attachment("公告.pdf", make_pdf(body))
    assert "Tender notice" in text and needs_ocr is False
    text, needs_ocr = parse_attachment("其他.zip", b"")
    assert text == "" and needs_ocr is False
