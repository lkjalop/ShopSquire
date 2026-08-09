"""Generate a complete, non-sealing packet for human slate review."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default="tests/golden/relevance_labels.json")
    parser.add_argument("--candidates", default="tmp/relevance_review_candidates.json")
    parser.add_argument("--markdown", default="tmp/relevance_human_review_packet.md")
    parser.add_argument("--template", default="tmp/relevance_human_review_template.json")
    parser.add_argument(
        "--review-type", choices=("independent", "owner"), default="independent",
    )
    parser.add_argument("--reviewer-id", default=None)
    args = parser.parse_args()
    labels_path = Path(args.labels)
    candidates_path = Path(args.candidates)
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    draft_cases = labels.get("cases") or {}
    template = {
        "schema_version": "relevance-human-review-v1",
        "labels_sha256": _sha(labels_path),
        "candidates_sha256": _sha(candidates_path),
        "reviewer": None,
        "reviewer_id": args.reviewer_id,
        "review_type": args.review_type,
        "independent": args.review_type == "independent",
        "status": "pending_human_review",
        "reviewed_at": None,
        "attestation": None,
        "rubric": {"2": "highly relevant", "1": "acceptable", "0": "explicitly irrelevant"},
        "cases": {},
    }
    lines = [
        (
            "# Independent human relevance review packet"
            if args.review_type == "independent"
            else "# Owner-reviewed development relevance packet"
        ),
        "",
        "This packet does not seal or change the corpus. Review every shown SKU against the query and grade the candidate slate: `2` highly relevant, `1` acceptable, `0` explicitly irrelevant.",
        "",
        f"- Labels SHA-256: `{template['labels_sha256']}`",
        f"- Candidate packet SHA-256: `{template['candidates_sha256']}`",
        (
            "- Required reviewer: an independent human; AI/automation identities are rejected by the production seal workflow."
            if args.review_type == "independent"
            else "- Review status: owner-reviewed development evidence only; it must not be described as independent or production-sealed."
        ),
        f"- Reviewer identifier: `{args.reviewer_id or 'TO_BE_RECORDED'}`",
        "",
    ]
    for case_id, slate in candidates.items():
        query = str((slate or {}).get("query") or "")
        draft = ((draft_cases.get(case_id) or {}).get("labels") or {})
        rows = []
        lines.extend([
            f"## {case_id}", "", f"Query: **{query}**", "",
            "| SKU | Candidate | Price | Current AI draft | Human grade | Notes |",
            "|---|---|---:|---:|---:|---|",
        ])
        for product in list((slate or {}).get("products") or []):
            sku = str(product.get("sku") or "")
            current = draft.get(sku)
            rows.append({
                "sku": sku,
                "name": product.get("name"),
                "price": product.get("price"),
                "currency": product.get("currency"),
                "current_ai_draft": current,
                "human_grade": None,
                "notes": None,
            })
            safe_name = str(product.get("name") or "").replace("|", "\\|")
            lines.append(
                f"| {sku} | {safe_name} | {product.get('currency') or ''} {product.get('price') or ''} | "
                f"{current if current is not None else 'UNLABELED'} |  |  |"
            )
        template["cases"][case_id] = {"query": query, "products": rows}
        lines.append("")
    Path(args.markdown).write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path(args.template).write_text(json.dumps(template, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "review_required",
        "case_count": len(template["cases"]),
        "product_count": sum(len(case["products"]) for case in template["cases"].values()),
        "markdown": args.markdown,
        "template": args.template,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
