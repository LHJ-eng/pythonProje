"""本地中文图片 OCR：RapidOCR + ONNX Runtime，图片校验与视觉分行。

第三方 OCR 库只在真正识别时导入，因此未安装 OCR 依赖时基础网页抓取仍可正常运行。
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import threading
import time

from .extractor import Extraction

COLUMNS = ["页码", "行号", "文字", "置信度", "左", "上", "右", "下"]
MAX_IMAGE_BYTES = 10_000_000
MAX_IMAGE_PIXELS = 20_000_000
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}
_DATA_URL = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")

_engine = None
_engine_lock = threading.Lock()
_infer_lock = threading.Lock()


class OCRError(ValueError):
    """图片数据无效、格式不支持或识别失败。"""


def decode_image_data(value: str) -> bytes:
    """把前端 FileReader 生成的 data URL（或纯 base64）还原为图片字节。"""
    raw = (value or "").strip()
    if not raw:
        raise OCRError("请选择需要识别的图片")
    raw = _DATA_URL.sub("", raw, count=1)
    raw = _WHITESPACE.sub("", raw)
    if not raw:
        raise OCRError("图片内容为空，请重新选择图片")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OCRError("图片数据不是有效的 base64 编码") from exc
    if not data:
        raise OCRError("图片内容为空，请重新选择图片")
    if len(data) > MAX_IMAGE_BYTES:
        raise OCRError("图片超过 10 MB 限制，请压缩后重试")
    return data


def _load_engine():
    """懒加载单例；初始化较慢，用锁避免并发重复加载。"""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise OCRError(
                    "未安装 OCR 依赖。请在项目目录执行："
                    "python -m pip install -r requirements-ocr.txt，然后重启服务"
                ) from exc
            try:
                _engine = RapidOCR()
            except Exception as exc:
                raise OCRError(f"OCR 引擎初始化失败：{exc}") from exc
    return _engine


def _load_image(data: bytes):
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise OCRError(
            "缺少 Pillow 依赖。请执行：python -m pip install -r requirements-ocr.txt"
        ) from exc
    if not data:
        raise OCRError("图片内容为空，请重新选择图片")
    if len(data) > MAX_IMAGE_BYTES:
        raise OCRError("图片超过 10 MB 限制，请压缩后重试")
    if b"<svg" in data[:512].lower():
        raise OCRError("不支持 SVG 图片，请使用 JPG、PNG 或 WebP")

    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = (probe.format or "").upper()
            if fmt not in SUPPORTED_FORMATS:
                raise OCRError(
                    f"不支持的图片格式：{fmt or '未知'}，仅支持 JPG、PNG、WebP"
                )
            if getattr(probe, "is_animated", False):
                raise OCRError("不支持动图，请使用单帧 JPG / PNG / WebP")
            width, height = probe.size
            if width <= 0 or height <= 0:
                raise OCRError("图片尺寸无效，请重新导出图片")
            if width * height > MAX_IMAGE_PIXELS:
                raise OCRError(
                    f"图片像素超过限制（最大 {MAX_IMAGE_PIXELS:,} 像素），"
                    "请缩小尺寸后重试"
                )
            probe.load()  # 强制解码，损坏文件会在这里抛出异常
            return ImageOps.exif_transpose(probe).convert("RGB")
    except OCRError:
        raise
    except Exception as exc:
        raise OCRError(
            "图片无法解析，请确认文件未损坏且为 JPG / PNG / WebP"
        ) from exc


def _box_bounds(box) -> tuple[int, int, int, int]:
    xs = [float(point[0]) for point in box]
    ys = [float(point[1]) for point in box]
    return int(round(min(xs))), int(round(min(ys))), int(round(max(xs))), int(round(max(ys)))


def _group_lines(blocks: list[dict]) -> list[list[dict]]:
    """按检测框的垂直重叠聚类成视觉行，再按 x 坐标排序。"""
    lines: list[dict] = []
    for block in sorted(blocks, key=lambda item: (item["top"], item["left"])):
        height = max(block["bottom"] - block["top"], 1)
        best_index = None
        best_overlap = 0.0
        for index, line in enumerate(lines):
            overlap = min(block["bottom"], line["bottom"]) - max(block["top"], line["top"])
            if overlap <= 0:
                continue
            ratio = overlap / min(height, max(line["bottom"] - line["top"], 1))
            center_gap = abs(block["center"] - line["center"])
            if ratio >= 0.5 and center_gap <= 0.5 * max(height, line["height"]):
                if ratio > best_overlap:
                    best_overlap = ratio
                    best_index = index
        if best_index is None:
            lines.append(
                {
                    "blocks": [block],
                    "top": block["top"],
                    "bottom": block["bottom"],
                    "center": block["center"],
                    "height": height,
                }
            )
        else:
            line = lines[best_index]
            line["blocks"].append(block)
            line["top"] = min(line["top"], block["top"])
            line["bottom"] = max(line["bottom"], block["bottom"])
            line["center"] = (line["top"] + line["bottom"]) / 2
            line["height"] = max(line["bottom"] - line["top"], 1)
    lines.sort(key=lambda line: (line["top"], min(b["left"] for b in line["blocks"])))
    for line in lines:
        line["blocks"].sort(key=lambda item: item["left"])
    return [line["blocks"] for line in lines]


def _merge_line(blocks: list[dict]) -> str:
    """同一视觉行内，明显空隙用 `` | `` 标记，模拟单元格间隔。"""
    heights = sorted(max(b["bottom"] - b["top"], 1) for b in blocks)
    median_height = heights[len(heights) // 2]
    gap_threshold = max(12.0, median_height * 0.9)
    parts = [blocks[0]["text"]]
    for previous, current in zip(blocks, blocks[1:]):
        gap = current["left"] - previous["right"]
        parts.append(" | " if gap > gap_threshold else " ")
        parts.append(current["text"])
    return "".join(parts).strip()


def _build_extraction(blocks: list[dict], page: int) -> Extraction:
    rows: list[list[str]] = []
    for line_index, line in enumerate(_group_lines(blocks), start=1):
        left = min(block["left"] for block in line)
        top = min(block["top"] for block in line)
        right = max(block["right"] for block in line)
        bottom = max(block["bottom"] for block in line)
        confidence = sum(block["score"] for block in line) / len(line)
        rows.append(
            [
                str(page),
                str(line_index),
                _merge_line(line),
                f"{confidence:.4f}",
                str(left),
                str(top),
                str(right),
                str(bottom),
            ]
        )
    return Extraction(columns=list(COLUMNS), rows=rows)


def recognize_image(data: bytes, *, page: int = 1) -> tuple[Extraction, dict]:
    """识别图片文字，返回按视觉行组织的表格数据与识别元数据。"""
    started = time.perf_counter()
    image = _load_image(data)

    try:
        import numpy as np
    except ImportError as exc:
        raise OCRError(
            "缺少 numpy 依赖。请执行：python -m pip install -r requirements-ocr.txt"
        ) from exc

    engine = _load_engine()
    try:
        with _infer_lock:
            output = engine(np.asarray(image))
    except OCRError:
        raise
    except Exception as exc:
        raise OCRError(f"图片文字识别失败：{exc}") from exc

    txts = [str(text) for text in (getattr(output, "txts", None) or [])]
    raw_boxes = getattr(output, "boxes", None)
    raw_scores = getattr(output, "scores", None) or []

    blocks: list[dict] = []
    for index, text in enumerate(txts):
        text = text.strip()
        if not text:
            continue
        try:
            box = raw_boxes[index]
            left, top, right, bottom = _box_bounds(box)
        except (TypeError, IndexError, ValueError):
            left = top = right = bottom = 0
        try:
            score = float(raw_scores[index])
        except (TypeError, IndexError, ValueError):
            score = 0.0
        blocks.append(
            {
                "text": text,
                "score": max(0.0, min(score, 1.0)),
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "center": (top + bottom) / 2,
            }
        )

    if not blocks:
        raise OCRError(
            "未从图片中识别到文字，请确认图片清晰、方向正确且包含中文或数字内容"
        )

    extraction = _build_extraction(blocks, page)
    scores = [block["score"] for block in blocks]
    width, height = image.size
    meta = {
        "engine": "RapidOCR",
        "image_width": width,
        "image_height": height,
        "page": page,
        "text_blocks": len(blocks),
        "lines": len(extraction.rows),
        "average_confidence": round(sum(scores) / len(scores), 4),
        "min_confidence": round(min(scores), 4),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    if meta["average_confidence"] < 0.8:
        extraction.warnings.append(
            "OCR 平均置信度偏低，图片可能模糊或倾斜，请对照原图复核"
        )
    low_blocks = sum(score < 0.6 for score in scores)
    if low_blocks:
        extraction.warnings.append(f"有 {low_blocks} 个文字块置信度低于 60%，建议人工校对")
    return extraction, meta
