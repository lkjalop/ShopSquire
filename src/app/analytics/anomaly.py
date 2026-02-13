from typing import List
import math
import random

def ewma(series: List[float], alpha: float = 0.2) -> float:
    if not series:
        return 0.0
    avg = series[0]
    for x in series[1:]:
        avg = alpha * x + (1 - alpha) * avg
    return avg


def is_anomaly(latest: float, series: List[float], alpha: float = 0.2, k: float = 3.0) -> bool:
    baseline = ewma(series, alpha)
    return latest > baseline * (1 + 0.1 * k)


def adaptive_ewma(series: List[float], min_alpha: float = 0.1, max_alpha: float = 0.4) -> float:
    """Adaptive EWMA that increases alpha when volatility rises."""
    if not series:
        return 0.0
    mean = sum(series) / max(len(series), 1)
    variance = sum((x - mean) ** 2 for x in series) / max(len(series), 1)
    std = math.sqrt(variance)
    volatility = 0.0 if mean == 0 else min(std / abs(mean), 1.0)
    alpha = min_alpha + (max_alpha - min_alpha) * volatility
    return ewma(series, alpha)


def _c_factor(n: int) -> float:
    if n <= 1:
        return 0.0
    return 2.0 * (math.log(n - 1) + 0.5772156649) - (2.0 * (n - 1) / n)


def isolation_forest_score(series: List[float], latest: float, trees: int = 25, sample_size: int = 32) -> float:
    """Lightweight isolation-forest style score for a 1D series."""
    if not series:
        return 0.0
    data = series[-max(len(series), 1):]
    n = min(len(data), sample_size)
    if n <= 1:
        return 0.0
    max_depth = int(math.ceil(math.log2(n + 1)))

    def path_length(x: float, samples: List[float], depth: int = 0) -> int:
        if len(samples) <= 1 or depth >= max_depth:
            return depth
        min_v = min(samples)
        max_v = max(samples)
        if min_v == max_v:
            return depth
        split = random.uniform(min_v, max_v)
        left = [v for v in samples if v < split]
        right = [v for v in samples if v >= split]
        if not left or not right:
            return depth + 1
        return path_length(x, left if x < split else right, depth + 1)

    lengths = []
    for _ in range(trees):
        sample = random.sample(data, n) if len(data) >= n else data
        lengths.append(path_length(latest, sample))

    avg_len = sum(lengths) / max(len(lengths), 1)
    c_n = _c_factor(n) or 1.0
    return 2 ** (-avg_len / c_n)
