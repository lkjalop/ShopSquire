"""Transformer-based fraud anomaly detection.

Uses a lightweight self-attention mechanism over user action sequences to learn
normal behavioral patterns and flag deviations.  No external ML libraries
required — implements a minimal transformer encoder in pure Python.

Architecture:
  - Action embedding: maps action types to fixed-dim vectors
  - Positional encoding: sinusoidal positions
  - Single-head self-attention layer
  - Anomaly scoring: reconstruction error against learned centroid
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Action vocabulary
# ---------------------------------------------------------------------------

ACTION_VOCAB: Dict[str, int] = {
    "page_view": 0,
    "search": 1,
    "add_to_cart": 2,
    "remove_from_cart": 3,
    "checkout_start": 4,
    "payment_submit": 5,
    "login": 6,
    "logout": 7,
    "account_update": 8,
    "password_change": 9,
    "address_change": 10,
    "rapid_click": 11,
    "api_call": 12,
    "file_upload": 13,
    "admin_access": 14,
    "export_data": 15,
}

EMBED_DIM = 16
_SEED = 42


# ---------------------------------------------------------------------------
# Deterministic pseudo-random for reproducible embeddings
# ---------------------------------------------------------------------------

def _lcg_float(seed: int) -> Tuple[float, int]:
    """Linear congruential generator returning float in [-0.5, 0.5]."""
    seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
    return (seed / 0x7FFFFFFF) - 0.5, seed


def _init_embeddings(vocab_size: int, dim: int) -> List[List[float]]:
    """Create deterministic embedding matrix."""
    seed = _SEED
    matrix: List[List[float]] = []
    for _ in range(vocab_size):
        row: List[float] = []
        for _ in range(dim):
            val, seed = _lcg_float(seed)
            row.append(val * 0.1)
        matrix.append(row)
    return matrix


_EMBEDDINGS = _init_embeddings(len(ACTION_VOCAB), EMBED_DIM)


# ---------------------------------------------------------------------------
# Positional encoding
# ---------------------------------------------------------------------------

def _positional_encoding(seq_len: int, dim: int) -> List[List[float]]:
    """Sinusoidal positional encoding."""
    pe: List[List[float]] = []
    for pos in range(seq_len):
        row = []
        for i in range(dim):
            if i % 2 == 0:
                row.append(math.sin(pos / (10000 ** (i / dim))))
            else:
                row.append(math.cos(pos / (10000 ** ((i - 1) / dim))))
        pe.append(row)
    return pe


# ---------------------------------------------------------------------------
# Self-attention (single-head)
# ---------------------------------------------------------------------------

def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _softmax(scores: List[float]) -> List[float]:
    max_s = max(scores) if scores else 0.0
    exps = [math.exp(s - max_s) for s in scores]
    total = sum(exps) + 1e-12
    return [e / total for e in exps]


def _vec_add(a: List[float], b: List[float]) -> List[float]:
    return [x + y for x, y in zip(a, b)]


def _vec_scale(v: List[float], s: float) -> List[float]:
    return [x * s for x in v]


def _self_attention(
    embeddings: List[List[float]],
) -> List[List[float]]:
    """Compute single-head self-attention over sequence embeddings.

    Q = K = V = embeddings (self-attention with no learned projection
    for simplicity — sufficient for anomaly scoring).
    """
    seq_len = len(embeddings)
    dim = len(embeddings[0]) if embeddings else 0
    if seq_len == 0 or dim == 0:
        return []

    scale = math.sqrt(dim)
    output: List[List[float]] = []

    for i in range(seq_len):
        # Compute attention scores for position i
        scores = [_dot(embeddings[i], embeddings[j]) / scale for j in range(seq_len)]
        weights = _softmax(scores)
        # Weighted sum of values
        out_vec = [0.0] * dim
        for j in range(seq_len):
            for d in range(dim):
                out_vec[d] += weights[j] * embeddings[j][d]
        output.append(out_vec)

    return output


# ---------------------------------------------------------------------------
# Anomaly scoring
# ---------------------------------------------------------------------------

def _compute_centroid(vectors: List[List[float]]) -> List[float]:
    """Compute centroid (mean) of a set of vectors."""
    if not vectors:
        return [0.0] * EMBED_DIM
    dim = len(vectors[0])
    centroid = [0.0] * dim
    for v in vectors:
        for d in range(dim):
            centroid[d] += v[d]
    n = len(vectors)
    return [c / n for c in centroid]


def _euclidean_distance(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


@dataclass
class AnomalyResult:
    is_anomalous: bool
    anomaly_score: float  # 0.0 = normal, higher = more anomalous
    sequence_length: int
    attention_entropy: float  # low entropy = concentrated attention = suspicious
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Normal behavior profiles (pre-computed centroids for common patterns)
# ---------------------------------------------------------------------------

# These represent "normal" shopping session patterns
_NORMAL_PATTERNS: List[List[str]] = [
    ["page_view", "search", "page_view", "add_to_cart", "checkout_start", "payment_submit"],
    ["login", "page_view", "search", "page_view", "page_view", "add_to_cart"],
    ["page_view", "page_view", "search", "page_view", "add_to_cart", "remove_from_cart", "add_to_cart"],
    ["login", "search", "page_view", "search", "add_to_cart", "checkout_start", "payment_submit"],
]


def _embed_sequence(actions: List[str]) -> List[List[float]]:
    """Convert action names to embedded + positionally-encoded vectors."""
    pe = _positional_encoding(len(actions), EMBED_DIM)
    embedded: List[List[float]] = []
    for i, action in enumerate(actions):
        idx = ACTION_VOCAB.get(action, 0)
        emb = _EMBEDDINGS[idx]
        embedded.append(_vec_add(emb, pe[i]))
    return embedded


def _get_normal_centroid() -> List[float]:
    """Compute average centroid from normal behavior patterns."""
    all_attended: List[List[float]] = []
    for pattern in _NORMAL_PATTERNS:
        embs = _embed_sequence(pattern)
        attended = _self_attention(embs)
        all_attended.extend(attended)
    return _compute_centroid(all_attended)


_NORMAL_CENTROID: List[float] = _get_normal_centroid()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_action_sequence(
    actions: List[str],
    *,
    anomaly_threshold: float = 0.35,
) -> AnomalyResult:
    """Score a sequence of user actions for anomalous behavior.

    Parameters
    ----------
    actions : List[str]
        Ordered list of action names (from ACTION_VOCAB).
    anomaly_threshold : float
        Distance threshold above which the sequence is flagged anomalous.

    Returns
    -------
    AnomalyResult
        Anomaly verdict with score and attention analysis.
    """
    if not actions:
        return AnomalyResult(
            is_anomalous=False,
            anomaly_score=0.0,
            sequence_length=0,
            attention_entropy=0.0,
            details={"error": "empty_sequence"},
        )

    # Embed and run self-attention
    embs = _embed_sequence(actions)
    attended = _self_attention(embs)
    if not attended:
        return AnomalyResult(
            is_anomalous=False, anomaly_score=0.0,
            sequence_length=len(actions), attention_entropy=0.0,
        )

    # Compute sequence centroid and distance from normal
    seq_centroid = _compute_centroid(attended)
    distance = _euclidean_distance(seq_centroid, _NORMAL_CENTROID)

    # Normalize distance to [0, 1] with sigmoid-like mapping
    anomaly_score = 1.0 - (1.0 / (1.0 + distance))

    # Attention entropy: measure how concentrated attention is
    # (low entropy → one token dominates → suspicious automated pattern)
    scale = math.sqrt(EMBED_DIM)
    entropy_sum = 0.0
    for i in range(len(embs)):
        scores = [_dot(embs[i], embs[j]) / scale for j in range(len(embs))]
        weights = _softmax(scores)
        ent = -sum(w * math.log(w + 1e-12) for w in weights)
        entropy_sum += ent
    avg_entropy = entropy_sum / len(embs)
    max_entropy = math.log(len(embs) + 1e-12)
    norm_entropy = avg_entropy / max_entropy if max_entropy > 0 else 0.0

    # Low entropy + high distance = more anomalous
    if norm_entropy < 0.5:
        anomaly_score = min(anomaly_score + 0.1, 1.0)

    is_anomalous = anomaly_score >= anomaly_threshold

    return AnomalyResult(
        is_anomalous=is_anomalous,
        anomaly_score=round(anomaly_score, 4),
        sequence_length=len(actions),
        attention_entropy=round(norm_entropy, 4),
        details={
            "distance_from_normal": round(distance, 4),
            "sequence_centroid_norm": round(math.sqrt(sum(x * x for x in seq_centroid)), 4),
            "actions": actions[:20],  # truncate for logging
        },
    )
