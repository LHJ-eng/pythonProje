"""OCR 模块测试：图片校验、视觉分行、置信度与缺失依赖提示。"""

from __future__ import annotations

import base64
import io
import sys

import pytest

from app import ocr
from app.extractor import Extraction


def _png_bytes(size: tuple[int, int] = (40, 30)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _box(left: int, top: int, right: int, bottom: int) -> list[list[int]]:
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


class _FakeOutput:
    def __init__(self, txts, boxes, scores):
        self.txts = txts
        self.boxes = boxes
        self.scores = scores


class _FakeEngine:
    def __init__(self, output: _FakeOutput) -> None:
        self.output = output
        self.calls = 0

    def __call__(self, image):
        assert getattr(image, "ndim", None) == 3
        self.calls += 1
        return self.output


def test_decode_data_url_and_plain_base64():
    payload = b"\x89PNG\r\n\x1a\nhello"
    encoded = base64.b64encode(payload).decode("ascii")

    assert ocr.decode_image_data(f"data:image/png;base64,{encoded}") == payload
    assert ocr.decode_image_data(encoded) == payload


def test_decode_rejects_invalid_base64():
    with pytest.raises(ocr.OCRError, match="base64"):
        ocr.decode_image_data("data:image/png;base64,不是base64!!")


def test_decode_rejects_empty_value():
    with pytest.raises(ocr.OCRError):
        ocr.decode_image_data("   ")


def test_recognize_groups_visual_lines_and_marks_cell_gaps(monkeypatch):
    output = _FakeOutput(
        txts=["姓名", "年龄", "张三", "30"],
        boxes=[
            _box(10, 10, 50, 30),
            _box(200, 12, 250, 32),
            _box(10, 50, 50, 70),
            _box(200, 50, 230, 70),
        ],
        scores=[0.99, 0.95, 0.90, 0.85],
    )
    engine = _FakeEngine(output)
    monkeypatch.setattr(ocr, "_load_engine", lambda: engine)

    extraction, meta = ocr.recognize_image(_png_bytes(), page=2)

    assert isinstance(extraction, Extraction)
    assert extraction.columns == ocr.COLUMNS
    assert len(extraction.rows) == 2
    assert extraction.rows[0][0] == "2"
    assert extraction.rows[0][1] == "1"
    assert extraction.rows[0][2] == "姓名 | 年龄"
    assert extraction.rows[1][2] == "张三 | 30"
    assert extraction.rows[0][4:] == ["10", "10", "250", "32"]
    assert meta["page"] == 2
    assert meta["text_blocks"] == 4
    assert meta["lines"] == 2
    assert meta["image_width"] == 40
    assert meta["image_height"] == 30
    assert meta["average_confidence"] == pytest.approx(0.9225)
    assert "image" not in meta and "data" not in meta
    assert engine.calls == 1


def test_recognize_keeps_adjacent_blocks_on_same_line(monkeypatch):
    output = _FakeOutput(
        txts=["2024", "年"],
        boxes=[_box(10, 10, 60, 30), _box(64, 11, 80, 30)],
        scores=[0.99, 0.99],
    )
    monkeypatch.setattr(ocr, "_load_engine", lambda: _FakeEngine(output))

    extraction, _ = ocr.recognize_image(_png_bytes())

    assert extraction.rows[0][2] == "2024 年"


def test_recognize_warns_on_low_confidence(monkeypatch):
    output = _FakeOutput(
        txts=["模糊文字"],
        boxes=[_box(10, 10, 80, 30)],
        scores=[0.42],
    )
    monkeypatch.setattr(ocr, "_load_engine", lambda: _FakeEngine(output))

    extraction, meta = ocr.recognize_image(_png_bytes())

    assert meta["average_confidence"] == pytest.approx(0.42)
    assert any("置信度偏低" in warning for warning in extraction.warnings)
    assert any("低于 60%" in warning for warning in extraction.warnings)


def test_recognize_rejects_image_without_text(monkeypatch):
    monkeypatch.setattr(
        ocr, "_load_engine", lambda: _FakeEngine(_FakeOutput([], [], []))
    )
    with pytest.raises(ocr.OCRError, match="未从图片中识别到文字"):
        ocr.recognize_image(_png_bytes())


def test_rejects_svg():
    with pytest.raises(ocr.OCRError, match="SVG"):
        ocr._load_image(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")


def test_rejects_damaged_image():
    with pytest.raises(ocr.OCRError, match="无法解析"):
        ocr._load_image(b"\xff\xd8\xff\xe0not-a-real-jpeg")


def test_rejects_animated_gif():
    from PIL import Image

    buffer = io.BytesIO()
    frames = [Image.new("RGB", (10, 10), "white"), Image.new("RGB", (10, 10), "black")]
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])

    with pytest.raises(ocr.OCRError, match="GIF"):
        ocr._load_image(buffer.getvalue())


def test_rejects_too_many_pixels(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ocr.OCRError, match="像素超过"):
        ocr._load_image(_png_bytes((20, 20)))


def test_rejects_oversized_bytes(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(ocr.OCRError, match="10 MB"):
        ocr._load_image(_png_bytes())


def test_missing_dependency_message_points_to_requirements(monkeypatch):
    monkeypatch.setattr(ocr, "_engine", None)
    monkeypatch.setitem(sys.modules, "rapidocr", None)

    with pytest.raises(ocr.OCRError, match="requirements-ocr"):
        ocr._load_engine()
