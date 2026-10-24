"""Validate local links in the current public entrypoints, without private artifacts."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    'README.md',
    'docs/portfolio/ENGINEERING_WALKTHROUGH.md',
    'docs/architecture/CURRENT_ARCHITECTURE_2026-10-23.md',
    'docs/REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md',
    'docs/EXECUTION_DELTA_AND_MVP_ROADMAP_2026-10-25.md',
    'docs/architecture/CURRENT_ARCHITECTURE_2026-10-25.md',
    'docs/PRICING_ACCEPTANCE_AND_REGIONAL_GROUNDING_2026-10-25.md',
)


def heading_ids(text: str) -> set[str]:
    """IDs used by these plain-text Markdown headings, including duplicates."""
    result: set[str] = set()
    counts: dict[str, int] = {}
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', text, re.M):
        base = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        count = counts.get(base, 0)
        counts[base] = count + 1
        result.add(base if count == 0 else f'{base}-{count}')
    return result


def check_links(root: Path = ROOT) -> tuple[int, list[str]]:
    checked = 0
    failures = []
    for name in DOCUMENTS:
        source = root / name
        if not source.is_file():
            failures.append(f'{name}: missing entrypoint')
            continue
        body = source.read_text(encoding='utf-8')
        for href in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', body):
            parts = urlsplit(href)
            if parts.scheme or parts.netloc:
                continue
            target = (source.parent / unquote(parts.path)).resolve() if parts.path else source
            if (not target.is_relative_to(root.resolve())
                    or '.artifacts' in target.relative_to(root.resolve()).parts):
                failures.append(f'{name}: non-public target {href}')
                continue
            if not target.is_file():
                failures.append(f'{name}: missing target {href}')
                continue
            if parts.fragment:
                text = target.read_text(encoding='utf-8-sig')
                if target.suffix == '.md':
                    valid = unquote(parts.fragment) in heading_ids(text)
                elif re.fullmatch(r'L\d+', parts.fragment):
                    valid = 1 <= int(parts.fragment[1:]) <= len(text.splitlines())
                else:
                    valid = False
                if not valid:
                    failures.append(f'{name}: invalid anchor {href}')
                    continue
            checked += 1
    return checked, failures


def main() -> int:
    checked, failures = check_links()
    for failure in failures:
        print(failure)
    print(f'{checked} local public links checked; {len(failures)} failures')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
