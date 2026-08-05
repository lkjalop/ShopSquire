from __future__ import annotations

import sys
import types

from src.app.services import cv_ocr


def test_tesseract_uses_one_native_pass_and_reconstructs_text(monkeypatch):
    calls = {"data": 0, "string": 0}

    image_module = types.ModuleType("PIL.Image")
    image_module.open = lambda _stream: object()
    pil_module = types.ModuleType("PIL")
    pil_module.Image = image_module

    tesseract = types.ModuleType("pytesseract")
    tesseract.Output = types.SimpleNamespace(DICT="dict")
    tesseract.pytesseract = types.SimpleNamespace(tesseract_cmd="")

    def _data(_image, *, output_type, timeout):
        calls["data"] += 1
        assert output_type == "dict"
        assert timeout == 5
        return {
            "text": ["Order", "", "ABC-123"],
            "conf": [95, -1, 90],
            "left": [1, 0, 2], "top": [1, 0, 2],
            "width": [10, 0, 20], "height": [5, 0, 5],
        }

    def _string(*_args, **_kwargs):
        calls["string"] += 1
        raise AssertionError("second native OCR pass must not run")

    tesseract.image_to_data = _data
    tesseract.image_to_string = _string
    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setitem(sys.modules, "pytesseract", tesseract)
    monkeypatch.delenv("CV_OCR_TIMEOUT_SEC", raising=False)

    result = cv_ocr._tesseract_ocr(b"fixture")
    assert result["text"] == "Order ABC-123"
    assert calls == {"data": 1, "string": 0}
