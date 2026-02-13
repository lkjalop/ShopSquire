from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Cluster:
    id: str
    size: int
    centroid_text: str
    members: List[str]
    label: Optional[str] = None


class _EmbedCache:
    def __init__(self, path: str = os.path.join("tmp", "embedding_cache.json")):
        self.path = path
        self._cache: Dict[str, List[float]] = {}
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
        except Exception:
            self._cache = {}

    def get(self, text: str) -> Optional[List[float]]:
        return self._cache.get(hashlib.sha256(text.encode("utf-8")).hexdigest())

    def set(self, text: str, vec: List[float]):
        self._cache[hashlib.sha256(text.encode("utf-8")).hexdigest()] = vec
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f)
        except Exception:
            pass


def _embed_batch(texts: List[str], model_name: str = "local-bge-mini") -> List[List[float]]:
    cache = _EmbedCache()
    vecs: List[List[float]] = []
    try:
        # Try sentence-transformers first
        from sentence_transformers import SentenceTransformer  # type: ignore

        st_model = None
        try:
            st_model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        except Exception:
            st_model = SentenceTransformer("all-MiniLM-L6-v2")
        for t in texts:
            cached = cache.get(t)
            if cached:
                vecs.append(cached)
                continue
            v = st_model.encode([t])[0].tolist()
            cache.set(t, v)
            vecs.append(v)
        return vecs
    except Exception:
        # Fallback deterministic hashing to vector
        for t in texts:
            cached = cache.get(t)
            if cached:
                vecs.append(cached)
                continue
            rnd = random.Random(hash(t) & 0xFFFFFFFF)
            v = [rnd.random() for _ in range(16)]
            cache.set(t, v)
            vecs.append(v)
        return vecs


def _cluster_embeddings(embeds: List[List[float]], min_cluster_size: int = 5) -> List[int]:
    try:
        import hdbscan  # type: ignore
        import numpy as np  # type: ignore
        from sklearn.decomposition import PCA  # type: ignore

        X = np.array(embeds)
        if X.shape[1] > 10:
            X = PCA(n_components=10, random_state=42).fit_transform(X)
        labels = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size).fit_predict(X)
        return labels.tolist()
    except Exception:
        # Fallback to KMeans
        try:
            from sklearn.cluster import KMeans  # type: ignore
            import numpy as np  # type: ignore

            X = np.array(embeds)
            k = max(1, min(5, len(embeds) // max(min_cluster_size, 1)))
            km = KMeans(n_clusters=k, n_init=5, random_state=42).fit(X)
            return km.labels_.tolist()
        except Exception:
            # Single cluster fallback
            return [0 for _ in embeds]


def _label_cluster(texts: List[str]) -> str:
    # Heuristic label by top keywords; avoid LLM dependency by default
    try:
        from collections import Counter
        words = []
        for t in texts:
            words.extend([w.lower() for w in t.split() if len(w) > 3])
        common = [w for (w, _) in Counter(words).most_common(3)]
        return " ".join(common) if common else (texts[0][:40] if texts else "misc")
    except Exception:
        return texts[0][:40] if texts else "misc"


class QueryClusterer:
    """Group similar queries for FAQ generation.

    - Embeddings: sentence-transformers (with cache) or hashed fallback
    - Clustering: HDBSCAN or KMeans fallback
    - Labeling: keyword heuristic; can be upgraded to zero-shot LLM
    """

    def cluster(self, queries: List[str], min_cluster_size: int = 5) -> List[Cluster]:
        if not queries:
            return []
        embeds = _embed_batch(queries)
        labels = _cluster_embeddings(embeds, min_cluster_size=min_cluster_size)
        by_label: Dict[int, List[Tuple[int, str]]] = {}
        for i, l in enumerate(labels):
            by_label.setdefault(int(l), []).append((i, queries[i]))
        clusters: List[Cluster] = []
        for lab, items in by_label.items():
            members = [t for (_, t) in items]
            centroid = members[0] if members else ""
            label = _label_cluster(members)
            clusters.append(Cluster(id=f"cl_{lab}", size=len(members), centroid_text=centroid, members=members, label=label))
        # Sort by size desc
        clusters.sort(key=lambda c: c.size, reverse=True)
        return clusters
