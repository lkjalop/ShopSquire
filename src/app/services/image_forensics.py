from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple


try:
    import numpy as np  # type: ignore
    from PIL import Image, ImageFilter, ImageOps, ImageStat  # type: ignore
except Exception:  # pragma: no cover - handled gracefully at runtime
    np = None  # type: ignore
    Image = None  # type: ignore

try:
    # Metrics are optional in unit tests
    from src.app.observability.metrics import record_cv_fraud
except Exception:  # pragma: no cover
    def record_cv_fraud(signal: str):  # type: ignore
        return None


@dataclass
class ForensicsResult:
    manipulation_score: float
    splice_score: float
    copy_move_score: float
    double_compress_score: float
    blur_score: float
    metadata_flags: List[str] = field(default_factory=list)
    masks: Dict[str, List[Dict[str, int]]] = field(default_factory=dict)
    hashes: Dict[str, str] = field(default_factory=dict)
    explanations: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class ImageForensicsService:
    """Image forensics including ELA, splice/copy-move, compression, blur, EXIF, perceptual hashes."""

    def analyze(self, image: bytes, context: Optional[Dict[str, Any]] = None) -> ForensicsResult:
        if np is None or Image is None:
            return ForensicsResult(
                manipulation_score=0.0,
                splice_score=0.0,
                copy_move_score=0.0,
                double_compress_score=0.0,
                blur_score=0.0,
                metadata_flags=["missing_deps"],
                explanations=["NumPy/Pillow not available"],
            )
        context = context or {}
        try:
            img = Image.open(BytesIO(image)).convert("RGB")
        except Exception as exc:  # pragma: no cover - validated by tests upstream
            return ForensicsResult(
                manipulation_score=0.0,
                splice_score=0.0,
                copy_move_score=0.0,
                double_compress_score=0.0,
                blur_score=0.0,
                metadata_flags=["invalid_image"],
                explanations=[f"Failed to open image: {exc}"],
            )

        # ELA pyramid and masks
        ela_stats, ela_mask_bboxes = self._compute_ela_pyramid(img)

        # Copy-move via block hashing
        copy_move_score, cm_bboxes = self._detect_copy_move(img)

        # Compression heuristics (double compression proxy) and format details
        double_compress_score, comp_details = self._compression_artifacts(img, ela_stats.get("ela_var_q85"))

        # Blur/noise metrics
        blur_score = self._blur_score(img)

        # Metadata flags
        metadata_flags, exif_details = self._metadata_flags(img)

        # Perceptual hashes
        hashes = self._compute_hashes(img)

        # Splice score (heuristic): strong ELA clusters + compression inconsistency
        splice_score = float(
            min(1.0, 0.7 * ela_stats.get("ela_cluster_strength", 0.0) + 0.3 * double_compress_score)
        )

        # Composite manipulation score
        manipulation_score = float(
            min(
                1.0,
                0.45 * splice_score
                + 0.3 * copy_move_score
                + 0.15 * double_compress_score
                + 0.10 * max(0.0, blur_score - 0.6),
            )
        )

        masks: Dict[str, List[Dict[str, int]]] = {
            "ela": ela_mask_bboxes,
            "copy_move": cm_bboxes,
        }

        explanations: List[str] = []
        if splice_score >= 0.8 and self._total_bbox_area(masks.get("ela", []), img.size) >= 0.08:
            explanations.append("ELA clusters indicate potential splice region ≥ 8% area")
            record_cv_fraud("image_splice")
        if copy_move_score >= 0.6:
            explanations.append("Copy-move duplicates detected via block-hash matches")
            record_cv_fraud("copy_move")
        if double_compress_score >= 0.7:
            explanations.append("Likely double JPEG compression detected")
            record_cv_fraud("double_compress")
        if blur_score >= 0.85:
            explanations.append("Image very blurry; request better capture")

        details = {
            "ela": ela_stats,
            "compression": comp_details,
            "exif": exif_details,
        }

        return ForensicsResult(
            manipulation_score=manipulation_score,
            splice_score=splice_score,
            copy_move_score=copy_move_score,
            double_compress_score=double_compress_score,
            blur_score=blur_score,
            metadata_flags=metadata_flags,
            masks=masks,
            hashes=hashes,
            explanations=explanations,
            details=details,
        )

    # Backward-compat wrapper
    def analyze_image(self, image_bytes: bytes) -> Dict[str, Any]:
        res = self.analyze(image_bytes)
        return {
            "manipulation_score": res.manipulation_score,
            "splice_score": res.splice_score,
            "copy_move_score": res.copy_move_score,
            "double_compress_score": res.double_compress_score,
            "blur_score": res.blur_score,
            "metadata": res.metadata_flags,
            "masks": res.masks,
            "hashes": res.hashes,
            "explanations": res.explanations,
            "details": res.details,
        }

    # -------------------- Implementation helpers --------------------

    def _compute_ela_pyramid(self, img: Image.Image) -> Tuple[Dict[str, Any], List[Dict[str, int]]]:
        arr = np.asarray(img, dtype=np.float32)
        # Keep pyramid small for performance while retaining sensitivity
        qualities = [95, 85]
        block = 16
        ela_maps = []
        for q in qualities:
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=q)
            buf.seek(0)
            resaved = Image.open(buf).convert("RGB")
            diff = np.abs(arr - np.asarray(resaved, dtype=np.float32))
            ela_maps.append(diff)
        ela_stack = np.stack(ela_maps, axis=0)  # (Q, H, W, 3)
        ela_mean = float(np.mean(ela_stack))
        ela_max = float(np.max(ela_stack))

        # Block-wise residuals for heatmap
        mean_map = ela_stack.mean(axis=(0, 3))  # (H, W)
        H, W = mean_map.shape
        # Robust threshold via z-score on residuals
        mu = float(mean_map.mean())
        sigma = float(mean_map.std() + 1e-6)
        z = (mean_map - mu) / sigma
        mask = (z >= 2.5).astype(np.uint8)
        bboxes = self._mask_to_bboxes(mask, min_block=block)
        # Combine area and intensity (mean z within mask)
        area = (mask.sum() / (H * W))
        intensity = float(max(0.0, min(1.0, (z[mask == 1].mean() / 5.0) if mask.sum() else 0.0)))
        cluster_strength = float(min(1.0, area * 6.0 + intensity * 0.6))

        stats = {
            "ela_mean": ela_mean,
            "ela_max": ela_max,
            "ela_cluster_strength": cluster_strength,
            "z_threshold": 2.5,
            "height": H,
            "width": W,
            # Provide var for q=85 to reuse in compression heuristic
            "ela_var_q85": float(np.var(ela_maps[1])) if len(ela_maps) > 1 else float(np.var(ela_maps[0])),
        }
        return stats, bboxes

    def _detect_copy_move(self, img: Image.Image) -> Tuple[float, List[Dict[str, int]]]:
        # Overlapping block hashing (dHash) with stride
        arr = np.asarray(img.convert("L"))
        h, w = arr.shape
        block = 24
        stride = 12
        hashes: Dict[str, List[Tuple[int, int]]] = {}

        def dhash(patch: np.ndarray) -> str:
            # 9x8 gradient hash
            small = Image.fromarray(patch).resize((9, 8), Image.BILINEAR)
            s = np.asarray(small, dtype=np.float32)
            diff = s[:, 1:] > s[:, :-1]
            bits = (diff.flatten()).astype(np.uint8)
            return ''.join('1' if b else '0' for b in bits)

        for y in range(0, h - block + 1, stride):
            for x in range(0, w - block + 1, stride):
                patch = arr[y : y + block, x : x + block]
                # Skip low-variance patches to reduce false positives on uniform areas
                if float(patch.var()) < 8.0:
                    continue
                key = dhash(patch)
                hashes.setdefault(key, []).append((x, y))

        # Find keys with multiple distinct positions far apart
        bboxes: List[Dict[str, int]] = []
        matches = 0
        for pts in hashes.values():
            if len(pts) < 2:
                continue
            pts = list(set(pts))
            for i in range(len(pts)):
                for j in range(i + 1, len(pts)):
                    (x1, y1), (x2, y2) = pts[i], pts[j]
                    if abs(x1 - x2) + abs(y1 - y2) >= block * 2:
                        matches += 1
                        bboxes.append(
                            {
                                "min_x": int(min(x1, x2)),
                                "min_y": int(min(y1, y2)),
                                "max_x": int(max(x1, x2) + block),
                                "max_y": int(max(y1, y2) + block),
                            }
                        )
        area_ratio = self._total_bbox_area(bboxes, (w, h))
        score = float(min(1.0, 0.15 + matches * 0.04 + area_ratio)) if matches else 0.0
        return score, bboxes[:10]

    def _compression_artifacts(self, img: Image.Image, ela_var_q85: Optional[float] = None) -> Tuple[float, Dict[str, Any]]:
        fmt = (img.format or "").upper() if hasattr(img, "format") else ""
        score = 0.0
        details: Dict[str, Any] = {"format": fmt}
        try:
            # Compare ELA at qualities widely spaced
            buf2 = BytesIO()
            img.save(buf2, format="JPEG", quality=70)
            buf2.seek(0)
            diff2 = np.abs(np.asarray(img, dtype=np.float32) - np.asarray(Image.open(buf2), dtype=np.float32))
            v1 = float(ela_var_q85) if ela_var_q85 is not None else float(np.var(np.abs(np.asarray(img, dtype=np.float32) - np.asarray(img, dtype=np.float32))))
            v2 = float(np.var(diff2))
            # If already compressed, structure of residuals tends to show higher disparity
            ratio = v2 / (v1 + 1e-6)
            score = float(max(0.0, min(1.0, (ratio - 1.1) / 1.3)))
            details.update({"ela_var_q85": v1, "ela_var_q70": v2, "var_ratio": ratio})
        except Exception:
            pass
        return score, details

    def _blur_score(self, img: Image.Image) -> float:
        gray = np.asarray(img.convert("L"), dtype=np.float32)
        # Laplacian via simple kernel
        kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
        from numpy.lib.stride_tricks import as_strided

        H, W = gray.shape
        k = 3
        shape = (H - k + 1, W - k + 1, k, k)
        strides = gray.strides * 2
        windows = as_strided(gray, shape=shape, strides=strides)
        conv = (windows * kernel).sum(axis=(2, 3))
        var = float(np.var(conv))
        # Normalize to 0..1 blur score where 1 is very blurry (low variance)
        ref = 500.0
        sharpness = min(1.0, var / ref)
        blur_score = float(1.0 - sharpness)
        return blur_score

    def _metadata_flags(self, img: Image.Image) -> Tuple[List[str], Dict[str, Any]]:
        flags: List[str] = []
        details: Dict[str, Any] = {}
        exif = None
        try:
            exif = img.getexif()
        except Exception:
            exif = None
        if not exif or len(exif) == 0:
            flags.append("missing_exif")
            return flags, details
        # Common EXIF fields
        try:
            software = str(exif.get(305, "")).lower()
            if any(s in software for s in ["photoshop", "gimp", "snapseed", "lightroom", "canva"]):
                flags.append("edited_software")
            details["software"] = software
        except Exception:
            pass
        for t in (271, 272, 306, 34853):  # Make, Model, DateTime, GPSInfo
            if t in exif:
                details[str(t)] = exif.get(t)
        return flags, details

    def _compute_hashes(self, img: Image.Image) -> Dict[str, str]:
        g = img.convert("L")
        return {
            "ahash": self._ahash(g),
            "dhash": self._dhash(g),
            "phash": self._phash(g),
        }

    def _ahash(self, g: Image.Image) -> str:
        small = g.resize((8, 8), Image.BILINEAR)
        arr = np.asarray(small, dtype=np.float32)
        m = arr.mean()
        bits = (arr >= m).astype(np.uint8).flatten()
        return ''.join('1' if b else '0' for b in bits)

    def _dhash(self, g: Image.Image) -> str:
        small = g.resize((9, 8), Image.BILINEAR)
        arr = np.asarray(small, dtype=np.float32)
        diff = arr[:, 1:] > arr[:, :-1]
        bits = diff.astype(np.uint8).flatten()
        return ''.join('1' if b else '0' for b in bits)

    def _phash(self, g: Image.Image) -> str:
        # Simple DCT-based 8x8
        small = g.resize((32, 32), Image.BILINEAR)
        f = np.asarray(small, dtype=np.float32)
        # 2D DCT via separable transform (naive, but fine for 32x32)
        def dct1(a: np.ndarray) -> np.ndarray:
            n = a.shape[0]
            k = np.arange(n).reshape(-1, 1)
            i = np.arange(n).reshape(1, -1)
            coef = np.cos(np.pi * (2 * i + 1) * k / (2 * n))
            alpha = np.where(k == 0, np.sqrt(1 / n), np.sqrt(2 / n))
            return alpha * (coef @ a)

        F = dct1(dct1(f).T).T
        low = F[:8, :8]
        med = np.median(low[1:, 1:])
        bits = (low[1:, 1:] > med).astype(np.uint8).flatten()
        return ''.join('1' if b else '0' for b in bits)

    def _mask_to_bboxes(self, mask: np.ndarray, min_block: int = 16) -> List[Dict[str, int]]:
        ys, xs = np.where(mask > 0)
        if ys.size == 0:
            return []
        return [
            {
                "min_x": int(xs.min()),
                "min_y": int(ys.min()),
                "max_x": int(xs.max()),
                "max_y": int(ys.max()),
            }
        ]

    def _total_bbox_area(self, bboxes: List[Dict[str, int]], size: Tuple[int, int]) -> float:
        if not bboxes:
            return 0.0
        w, h = size
        total = 0
        for b in bboxes:
            total += max(0, b["max_x"] - b["min_x"]) * max(0, b["max_y"] - b["min_y"])
        return float(total) / float(max(1, w * h))

