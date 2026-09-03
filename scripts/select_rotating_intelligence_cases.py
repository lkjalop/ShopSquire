"""Select a reproducible unfamiliar-title certificate from Steam's live store feed.

The selected names are deliberately not application fixtures.  A seed makes the
run reproducible, while the recorded feed hash proves which changing upstream
population was sampled.  Search results and store metadata are test inputs, not
procurement evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


FEED_URL = "https://store.steampowered.com/api/featuredcategories"
DETAILS_URL = "https://store.steampowered.com/api/appdetails"
SCAN_ROOTS = ("config", "src", "tests", "frontend/e2e")
TEXT_SUFFIXES = {".json", ".py", ".ts", ".tsx", ".md", ".yaml", ".yml"}


def _repository_corpus(repo: Path) -> str:
    chunks: list[str] = []
    for root_name in SCAN_ROOTS:
        root = repo / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                try:
                    chunks.append(path.read_text(encoding="utf-8", errors="ignore").casefold())
                except OSError:
                    continue
    return "\n".join(chunks)


def _requirement_completeness(pc: Any) -> str:
    if not isinstance(pc, dict):
        return "none"
    minimum = bool(str(pc.get("minimum") or "").strip())
    recommended = bool(str(pc.get("recommended") or "").strip())
    return "complete" if minimum and recommended else "partial" if minimum or recommended else "none"


def fetch_official_population(client: httpx.Client) -> list[dict[str, Any]]:
    response = client.get(FEED_URL, params={"cc": "au", "l": "english"})
    response.raise_for_status()
    feed = response.json()
    rows: dict[int, dict[str, Any]] = {}
    for group in ("new_releases", "top_sellers", "coming_soon"):
        items = ((feed.get(group) or {}).get("items") or []) if isinstance(feed, dict) else []
        for item in items:
            if isinstance(item, dict) and item.get("id") and item.get("name"):
                rows[int(item["id"])] = {
                    "appid": int(item["id"]), "title": str(item["name"]),
                    "feed_group": group,
                }
    resolved: list[dict[str, Any]] = []
    for row in rows.values():
        detail_response = client.get(
            DETAILS_URL, params={"appids": row["appid"], "cc": "au", "l": "english"},
        )
        detail_response.raise_for_status()
        wrapper = detail_response.json().get(str(row["appid"])) or {}
        data = wrapper.get("data") if wrapper.get("success") else None
        if not isinstance(data, dict) or str(data.get("type") or "game") != "game":
            continue
        release = data.get("release_date") if isinstance(data.get("release_date"), dict) else {}
        publishers = data.get("publishers") if isinstance(data.get("publishers"), list) else []
        resolved.append({
            **row,
            "title": str(data.get("name") or row["title"]),
            "publisher": str(publishers[0]) if publishers else None,
            "release_state": "unreleased" if release.get("coming_soon") else "released",
            "release_date": release.get("date"),
            "requirements_completeness": _requirement_completeness(data.get("pc_requirements")),
            "source_url": f"https://store.steampowered.com/app/{row['appid']}/",
        })
    return resolved


def _typo(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", title)
    target = max(words, key=len, default=title)
    if len(target) < 5:
        return title + "x"
    middle = len(target) // 2
    mutated = target[:middle] + target[middle + 1:]
    return title.replace(target, mutated, 1)


def select_cases(population: list[dict[str, Any]], *, corpus: str, seed: str, count: int) -> list[dict[str, Any]]:
    eligible = [row for row in population if row["title"].casefold() not in corpus]
    rng = random.Random(seed)
    rng.shuffle(eligible)
    if len(eligible) < count:
        raise RuntimeError(f"official feed yielded only {len(eligible)} unfamiliar titles; need {count}")

    def take(predicate, scenario: str) -> None:
        for index, row in enumerate(eligible):
            if predicate(row):
                chosen.append({**eligible.pop(index), "scenario": scenario})
                return

    chosen: list[dict[str, Any]] = []
    take(lambda row: row["release_state"] == "unreleased", "future_release")
    take(lambda row: row["requirements_completeness"] != "complete", "incomplete_requirements")
    take(lambda row: bool(re.search(r"[^A-Za-z0-9 ]", row["title"])), "punctuation")
    while eligible and len(chosen) < count:
        chosen.append({**eligible.pop(), "scenario": "recent_unfamiliar"})
    if not chosen:
        raise RuntimeError("no unfamiliar official-feed titles selected")
    # Make one positive case a bounded typo without teaching the application an alias.
    typo_index = next((i for i, row in enumerate(chosen) if len(row["title"]) >= 5), 0)
    chosen[typo_index]["query_title"] = _typo(chosen[typo_index]["title"])
    chosen[typo_index]["scenario"] += "+typo"
    for row in chosen:
        row.setdefault("query_title", row["title"])
    fabricated = "Unreleased Project " + hashlib.sha256((seed + "negative").encode()).hexdigest()[:10].upper()
    chosen.append({
        "scenario": "fabricated_negative", "title": fabricated, "query_title": fabricated,
        "appid": None, "publisher": None, "release_state": "unknown",
        "release_date": None, "requirements_completeness": "none", "source_url": None,
    })
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    with httpx.Client(timeout=15, follow_redirects=False, headers={
        "User-Agent": "ShopSquireRotatingCertificate/1.0",
    }) as client:
        population = fetch_official_population(client)
    population_json = json.dumps(population, sort_keys=True, separators=(",", ":"))
    cases = select_cases(
        population, corpus=_repository_corpus(repo), seed=args.seed, count=max(1, min(args.count, 8)),
    )
    artifact = {
        "schema_version": "rotating-intelligence-certificate.v1",
        "seed": args.seed,
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "official_feed": FEED_URL,
        "population_count": len(population),
        "population_sha256": hashlib.sha256(population_json.encode()).hexdigest(),
        "cases": cases,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output), "seed": args.seed, "population": len(population),
        "selected": [row["query_title"] for row in cases],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
