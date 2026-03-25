"""GNN Fraud Detector — graph neural network-based fraud ring detection.

Layers ML-based fraud scoring on top of the Neo4j graph signals in neo4j_graph.py.

Architecture:
1. **Feature extraction**: Pull subgraph features from Neo4j (node degrees,
   shared address counts, device overlap, velocity signals)
2. **GNN inference**: Simple 2-layer GraphSAGE-style model that classifies
   account nodes as fraud / legitimate based on neighborhood features
3. **Training pipeline**: Offline training on labeled fraud data
4. **Integration**: Adds GNN risk score to the existing fraud_scorer pipeline

When PyG (torch_geometric) is unavailable, falls back to heuristic subgraph
scoring that mimics GNN behavior using handcrafted features.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

try:
    from torch_geometric.nn import SAGEConv  # type: ignore
    from torch_geometric.data import Data  # type: ignore
    _HAS_PYG = True
except ImportError:
    _HAS_PYG = False

import logging as _logging
_gnn_log = _logging.getLogger(__name__)
_gnn_log.info(
    "[GNNFraudDetector] ML module inventory — numpy=%s torch=%s pyg=%s",
    _HAS_NUMPY,
    _HAS_TORCH,
    _HAS_PYG,
)


@dataclass
class SubgraphFeatures:
    """Features extracted from a Neo4j subgraph around a target account."""
    account_id: str
    degree: int = 0                     # direct neighbor count
    shared_address_count: int = 0       # addresses shared with other accounts
    shared_device_count: int = 0        # devices shared with other accounts
    shared_ip_count: int = 0            # IPs shared with other accounts
    transaction_velocity_24h: float = 0.0  # orders in last 24h
    avg_neighbor_degree: float = 0.0    # average degree of 1-hop neighbors
    max_ring_size: int = 0              # largest connected component in 2-hop neighborhood
    account_age_days: float = 0.0
    chargeback_rate: float = 0.0        # historical chargeback ratio

    def to_vector(self) -> List[float]:
        """Convert to numeric feature vector for GNN input."""
        return [
            float(self.degree),
            float(self.shared_address_count),
            float(self.shared_device_count),
            float(self.shared_ip_count),
            self.transaction_velocity_24h,
            self.avg_neighbor_degree,
            float(self.max_ring_size),
            self.account_age_days,
            self.chargeback_rate,
        ]


FEATURE_DIM = 9  # Length of SubgraphFeatures.to_vector()


# ── Neo4j feature extraction ──

def extract_subgraph_features(account_id: str) -> SubgraphFeatures:
    """Extract features from Neo4j for a target account.

    Falls back to zero features when Neo4j is unavailable.
    """
    features = SubgraphFeatures(account_id=account_id)

    try:
        from src.app.services.neo4j_graph import _get_driver, _enabled  # noqa: F811

        if not _enabled():
            return features

        driver = _get_driver()
        if not driver:
            return features

        query = """
        MATCH (a:Account {id: $account_id})
        OPTIONAL MATCH (a)-[:USES_ADDRESS]->(addr)<-[:USES_ADDRESS]-(other:Account)
        WITH a, count(DISTINCT addr) AS shared_addr, count(DISTINCT other) AS degree
        OPTIONAL MATCH (a)-[:USES_DEVICE]->(dev)<-[:USES_DEVICE]-(other2:Account)
        WITH a, shared_addr, degree, count(DISTINCT dev) AS shared_dev
        OPTIONAL MATCH (a)-[:FROM_IP]->(ip)<-[:FROM_IP]-(other3:Account)
        RETURN shared_addr, degree, count(DISTINCT ip) AS shared_ip, shared_dev
        """
        with driver.session() as session:
            result = session.run(query, account_id=account_id)
            record = result.single()
            if record:
                features.shared_address_count = record.get("shared_addr", 0) or 0
                features.degree = record.get("degree", 0) or 0
                features.shared_device_count = record.get("shared_dev", 0) or 0
                features.shared_ip_count = record.get("shared_ip", 0) or 0
    except Exception:
        pass

    # Adapter path for lightweight graph retrieval when Neo4j is disabled.
    try:
        from src.app.services.graph_retrieval import get_graph_adapter

        adapter = get_graph_adapter()
        rel = adapter.related_entities(node_type="account", node_id=account_id, limit=20)
        if rel:
            features.max_ring_size = max(features.max_ring_size, len(rel))
            avg_w = sum(float(r.get("weight") or 0.0) for r in rel) / float(max(1, len(rel)))
            features.avg_neighbor_degree = max(features.avg_neighbor_degree, avg_w * 10.0)
    except Exception:
        pass

    # DB fallback — query orders table for shared device/IP signals when both
    # Neo4j and graph_retrieval return zero features.
    if features.degree == 0 and features.shared_device_count == 0 and features.shared_ip_count == 0:
        try:
            from src.app.models.db import db_session
            from sqlalchemy import text as _sql

            with db_session() as _db:
                # Shared device fingerprint count
                row_dev = _db.execute(
                    _sql(
                        "SELECT COUNT(DISTINCT o2.account_id) AS shared "
                        "FROM orders o1 "
                        "JOIN orders o2 ON o2.device_fingerprint = o1.device_fingerprint "
                        "  AND o2.account_id <> o1.account_id "
                        "WHERE o1.account_id = :aid AND o1.device_fingerprint IS NOT NULL "
                        "LIMIT 1"
                    ),
                    {"aid": account_id},
                ).fetchone()
                if row_dev and row_dev[0]:
                    features.shared_device_count = int(row_dev[0])
                    features.degree = max(features.degree, features.shared_device_count)

                # Shared IP count
                row_ip = _db.execute(
                    _sql(
                        "SELECT COUNT(DISTINCT o2.account_id) AS shared "
                        "FROM orders o1 "
                        "JOIN orders o2 ON o2.ip_address = o1.ip_address "
                        "  AND o2.account_id <> o1.account_id "
                        "WHERE o1.account_id = :aid AND o1.ip_address IS NOT NULL "
                        "LIMIT 1"
                    ),
                    {"aid": account_id},
                ).fetchone()
                if row_ip and row_ip[0]:
                    features.shared_ip_count = int(row_ip[0])
                    features.degree = max(features.degree, features.shared_ip_count)

                # Transaction velocity last 24h
                row_vel = _db.execute(
                    _sql(
                        "SELECT COUNT(*) FROM orders "
                        "WHERE account_id = :aid "
                        "AND created_at >= NOW() - INTERVAL '24 hours'"
                    ),
                    {"aid": account_id},
                ).fetchone()
                if row_vel and row_vel[0]:
                    features.transaction_velocity_24h = float(row_vel[0])
        except Exception:
            pass

    return features


# ── GNN Model (when PyG is available) ──

if _HAS_PYG and _HAS_TORCH:
    class FraudGNN(nn.Module):
        """2-layer GraphSAGE for binary fraud classification."""

        def __init__(self, in_channels: int = FEATURE_DIM, hidden: int = 32):
            super().__init__()
            self.conv1 = SAGEConv(in_channels, hidden)
            self.conv2 = SAGEConv(hidden, 2)  # 2 classes: legit, fraud

        def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
            x = self.conv1(x, edge_index)
            x = F.relu(x)
            x = F.dropout(x, p=0.3, training=self.training)
            x = self.conv2(x, edge_index)
            return F.log_softmax(x, dim=1)

    def _load_model() -> Optional[FraudGNN]:
        """Load a pretrained GNN model if available."""
        model_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "models", "fraud_gnn.pt"
        )
        model_path = os.path.normpath(model_path)
        if not os.path.isfile(model_path):
            return None
        model = FraudGNN()
        model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
        model.eval()
        return model

else:
    def _load_model():
        return None


# ── Heuristic fallback (no PyG) ──

def _heuristic_fraud_score(features: SubgraphFeatures) -> float:
    """Heuristic GNN-analog scoring when PyG is unavailable.

    Combines subgraph features into a risk score using domain-weighted rules.
    """
    risk = 0.0

    # Shared addresses are strong fraud signal
    if features.shared_address_count >= 3:
        risk += 0.25
    elif features.shared_address_count >= 1:
        risk += 0.10

    # Shared devices
    if features.shared_device_count >= 3:
        risk += 0.20
    elif features.shared_device_count >= 1:
        risk += 0.08

    # Shared IPs
    if features.shared_ip_count >= 5:
        risk += 0.15
    elif features.shared_ip_count >= 2:
        risk += 0.07

    # High degree = many connections
    if features.degree >= 10:
        risk += 0.15
    elif features.degree >= 5:
        risk += 0.08

    # Large ring component
    if features.max_ring_size >= 10:
        risk += 0.20
    elif features.max_ring_size >= 5:
        risk += 0.10

    # Transaction velocity
    if features.transaction_velocity_24h >= 5:
        risk += 0.15
    elif features.transaction_velocity_24h >= 3:
        risk += 0.08

    # New account
    if features.account_age_days < 7:
        risk += 0.10
    elif features.account_age_days < 30:
        risk += 0.05

    # Historical chargeback
    risk += min(features.chargeback_rate * 0.5, 0.3)

    return min(risk, 1.0)


# ── Public API ──

@dataclass
class GNNFraudResult:
    """Result from GNN fraud detection."""
    account_id: str
    gnn_score: float = 0.0         # 0-1 fraud probability
    method: str = "heuristic"       # "gnn" or "heuristic"
    features_used: Dict[str, Any] = field(default_factory=dict)
    ring_detected: bool = False
    explanation: str = ""


def predict_fraud_risk(account_id: str) -> GNNFraudResult:
    """Predict fraud risk for an account using GNN or heuristic fallback.

    1. Extracts subgraph features from Neo4j
    2. If PyG + trained model available → GNN inference
    3. Otherwise → heuristic scoring
    """
    features = extract_subgraph_features(account_id)
    result = GNNFraudResult(
        account_id=account_id,
        features_used={
            "degree": features.degree,
            "shared_address": features.shared_address_count,
            "shared_device": features.shared_device_count,
            "shared_ip": features.shared_ip_count,
            "velocity_24h": features.transaction_velocity_24h,
            "ring_size": features.max_ring_size,
        },
    )

    # Try GNN model first
    model = _load_model()
    if model is not None and _HAS_TORCH:
        try:
            x = torch.tensor([features.to_vector()], dtype=torch.float32)
            # Single node, no edges in single-inference mode
            edge_index = torch.zeros((2, 0), dtype=torch.long)
            with torch.no_grad():
                out = model(x, edge_index)
                probs = torch.exp(out)[0]
                fraud_prob = float(probs[1])
            result.gnn_score = fraud_prob
            result.method = "gnn"
        except Exception:
            result.gnn_score = _heuristic_fraud_score(features)
            result.method = "heuristic"
    else:
        result.gnn_score = _heuristic_fraud_score(features)
        result.method = "heuristic"

    result.ring_detected = features.max_ring_size >= 5 or features.shared_address_count >= 3

    # Build explanation
    reasons = []
    if features.shared_address_count >= 2:
        reasons.append(f"{features.shared_address_count} shared shipping addresses")
    if features.shared_device_count >= 2:
        reasons.append(f"{features.shared_device_count} shared devices")
    if features.max_ring_size >= 5:
        reasons.append(f"part of {features.max_ring_size}-node ring")
    if features.transaction_velocity_24h >= 3:
        reasons.append(f"{features.transaction_velocity_24h:.0f} orders in 24h")
    if features.account_age_days < 7:
        reasons.append("new account (<7 days)")
    if reasons:
        result.explanation = f"Risk factors: {'; '.join(reasons)}"
    else:
        result.explanation = "No significant risk factors detected"

    return result
