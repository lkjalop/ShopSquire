#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
from typing import List, Tuple

from src.app.analytics.xgb_intent import train


def read_dataset(path: str) -> List[Tuple[str, str]]:
    data: List[Tuple[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Expect columns: text,label
        for row in reader:
            text = (row.get("text") or "").strip()
            label = (row.get("label") or "").strip()
            if not text or not label:
                continue
            data.append((text, label))
    return data


def main():
    ap = argparse.ArgumentParser(description="Train XGB/GB intent classifier and persist to models/xgb_intent.pkl")
    ap.add_argument("--input", "-i", default=os.path.join("data", "xgb_intent_dataset.csv"), help="CSV path with columns text,label")
    args = ap.parse_args()
    ds = read_dataset(args.input)
    if not ds:
        print("No data found. Provide a CSV with columns text,label.")
        return 1
    out = train(ds)
    if out.get("error"):
        print("Training failed. Ensure xgboost or scikit-learn are installed.")
        return 1
    print(f"Model trained. Labels={out.get('labels')} vocab_size={out.get('vocab_size')}")
    print("Saved to models/xgb_intent.pkl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
