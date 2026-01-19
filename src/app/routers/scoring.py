import json
import os
import time
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/v1/admin/scoring", tags=["admin-scoring"])


def _policy_path() -> str:
    return os.path.join("config", "security", "taxonomy", "risk_correlation_policy.json")


def _versions_dir() -> str:
    p = os.path.join("config", "security", "versions")
    os.makedirs(p, exist_ok=True)
    return p


@router.get("/weights")
def get_scoring_weights() -> Dict:
    with open(_policy_path(), "r", encoding="utf-8") as f:
        return json.load(f).get("weights", {})


@router.post("/weights")
def set_scoring_weights(weights: Dict) -> Dict:
    path = _policy_path()
    with open(path, "r", encoding="utf-8") as f:
        current = json.load(f)
    current["weights"] = weights
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return {"updated": True}


@router.post("/update")
def scoring_update(payload: Dict) -> Dict:
    # Update entire policy and write a version
    path = _policy_path()
    timestamp = int(time.time())
    with open(path, "r", encoding="utf-8") as f:
        current = json.load(f)
    new_policy = {**current, **payload}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(new_policy, f, ensure_ascii=False, indent=2)
    version_file = os.path.join(_versions_dir(), f"risk_correlation_policy_{timestamp}.json")
    with open(version_file, "w", encoding="utf-8") as vf:
        json.dump(new_policy, vf, ensure_ascii=False, indent=2)
    return {"version": timestamp}


@router.get("/versions")
def scoring_versions() -> Dict:
    files = [f for f in os.listdir(_versions_dir()) if f.startswith("risk_correlation_policy_")]
    return {"versions": files}


@router.get("/diff")
def scoring_diff(a: str, b: str) -> Dict:
    dirp = _versions_dir()
    with open(os.path.join(dirp, a), "r", encoding="utf-8") as fa:
        pa = json.load(fa)
    with open(os.path.join(dirp, b), "r", encoding="utf-8") as fb:
        pb = json.load(fb)
    return {"diff": {k: {"a": pa.get(k), "b": pb.get(k)} for k in set(pa.keys()) | set(pb.keys())}}


@router.post("/rollback")
class RollbackReq(BaseModel):
    version_file: str


@router.post("/rollback")
def scoring_rollback(req: RollbackReq) -> Dict:
    dirp = _versions_dir()
    src = os.path.join(dirp, req.version_file)
    if not os.path.exists(src):
        raise HTTPException(status_code=404, detail="Version not found")
    with open(src, "r", encoding="utf-8") as f:
        policy = json.load(f)
    with open(_policy_path(), "w", encoding="utf-8") as wf:
        json.dump(policy, wf, ensure_ascii=False, indent=2)
    return {"rolled_back": True}
