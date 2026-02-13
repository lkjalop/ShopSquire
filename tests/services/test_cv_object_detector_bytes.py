from io import BytesIO


def _png_bytes() -> bytes:
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"PIL required for this test: {exc}")

    img = Image.new("RGB", (64, 64), (255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_cv_object_detector_converts_bytes_to_numpy_array():
    try:
        import numpy as np  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"numpy required for this test: {exc}")

    from src.app.services.cv_object_detector import CVObjectDetector

    class FakeModel:
        def __init__(self):
            self.last_inp = None

        def __call__(self, inp):
            self.last_inp = inp
            return []

    detector = CVObjectDetector(model_path=None)
    fake = FakeModel()
    detector.model = fake

    detections = detector.detect(_png_bytes())
    assert detections == []
    assert isinstance(fake.last_inp, np.ndarray)
    assert fake.last_inp.ndim == 3

