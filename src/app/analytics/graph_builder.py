from __future__ import annotations

import hashlib
from typing import Dict, Any, List, Tuple


def _hash(val: str | None) -> str | None:
    if not val:
        return None
    return hashlib.sha256(val.encode("utf-8")).hexdigest()[:16]


def build_edges(event: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    edges: List[Tuple[str, str, str]] = []
    user_id = event.get("user_id") or event.get("uid")
    if not user_id:
        return edges
    user_node = f"user:{_hash(str(user_id))}"
    edges.extend(_build_edges_for_user(user_node, event))
    return edges


def _build_edges_for_user(user_node: str, event: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    edges: List[Tuple[str, str, str]] = []
    device = event.get("device_id_hash") or event.get("device_fingerprint")
    address = event.get("address_hash") or event.get("shipping_address_hash")
    payment = event.get("payment_token") or event.get("card_fingerprint")
    phash = event.get("phash")

    if device:
        edges.append((user_node, "USED_DEVICE", f"device:{_hash(str(device))}"))
    if address:
        edges.append((user_node, "USED_ADDRESS", f"address:{_hash(str(address))}"))
    if payment:
        edges.append((user_node, "PAID_WITH", f"payment:{_hash(str(payment))}"))
    if phash:
        edges.append((user_node, "SHARED_IMAGE", f"phash:{_hash(str(phash))}"))
    return edges


def build_graph(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    degrees: Dict[str, int] = {}

    for event in events:
        edge_list = build_edges(event)
        for src, rel, dst in edge_list:
            nodes.setdefault(src, {"id": src, "type": src.split(":")[0]})
            nodes.setdefault(dst, {"id": dst, "type": dst.split(":")[0]})
            edges.append({"source": src, "target": dst, "relation": rel})
            degrees[src] = degrees.get(src, 0) + 1
            degrees[dst] = degrees.get(dst, 0) + 1

    ring_nodes = [n for n, deg in degrees.items() if deg >= 3 and n.startswith(("device:", "address:", "payment:", "phash:"))]

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "ring_candidates": ring_nodes[:50],
        "ring_candidate_count": len(ring_nodes),
    }
