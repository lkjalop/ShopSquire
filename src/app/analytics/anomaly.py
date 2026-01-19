from typing import List

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
