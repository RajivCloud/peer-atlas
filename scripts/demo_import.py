"""Demo: parse a Discord paste and show what the extractors find.

Usage (from the project folder, with .venv active):
    python scripts/demo_import.py data/paste_sample.txt                  # rules only (free)
    python scripts/demo_import.py data/paste_sample.txt --engine claude  # Claude
    python scripts/demo_import.py data/paste_sample.txt --engine compare # both, side by side

Read-only: prints tables and writes nothing to the database.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "core" can be imported
sys.stdout.reconfigure(encoding="utf-8")  # Windows console + names in other scripts

import pandas as pd

from core.extract import build_peers, display_location
from core.ingest import parse_paste

pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 30)
pd.set_option("display.max_rows", 500)


def summary(label: str, peers: list[dict]) -> None:
    n = len(peers)
    def count(k): return f"{sum(1 for p in peers if p.get(k))}/{n}"
    print(f"\n[{label}] people: {n} | name {count('name')} | location {count('location_raw')} | "
          f"LinkedIn {count('linkedin_url')} | role {count('role')} | company {count('company')} | "
          f"need review {sum(p['needs_review'] for p in peers)}/{n}")


def show(peers: list[dict]) -> None:
    rows = [{
        "Handle": p["discord_handle"],
        "Name": p["name"],
        "Location": display_location(p),
        "Role": p["role"],
        "Company": p["company"],
        "LinkedIn": "✓" if p["linkedin_url"] else "",
        "Check": "⚠" if p["needs_review"] else "",
    } for p in peers]
    print(pd.DataFrame(rows).fillna("").to_string(index=False))


def compare(rules: list[dict], claude: list[dict]) -> None:
    by_handle = {p["discord_handle"]: p for p in rules}
    rows = []
    for c in claude:
        r = by_handle.get(c["discord_handle"], {})
        rows.append({
            "Handle": c["discord_handle"],
            "Location (rules)": r.get("location_raw"),
            "Location (Claude)": display_location(c),
            "Role (rules)": r.get("role"),
            "Role (Claude)": c.get("role"),
        })
    print(pd.DataFrame(rows).fillna("").to_string(index=False))
    only_rules = sorted(set(by_handle) - {c["discord_handle"] for c in claude})
    if only_rules:
        print("\nRules counted these as intros, Claude didn't:", ", ".join(only_rules))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="data/paste_sample.txt")
    ap.add_argument("--engine", choices=["rules", "claude", "compare"], default="rules")
    args = ap.parse_args()

    messages = parse_paste(Path(args.path).read_text(encoding="utf-8-sig"))
    print(f"Parsed {len(messages)} messages ({sum(1 for m in messages if m['embed'])} with a LinkedIn preview)\n")

    rules = build_peers(messages) if args.engine in ("rules", "compare") else None
    claude = None
    if args.engine in ("claude", "compare"):
        from core.claude_extract import ClaudeExtractor
        extractor = ClaudeExtractor(on_progress=lambda d, t: print(f"  Claude: {d}/{t} messages", flush=True))
        claude = build_peers(messages, extractor=extractor)
        cost = extractor.estimated_cost
        print(f"\nModel {extractor.model}: {extractor.input_tokens:,} input + {extractor.output_tokens:,} "
              f"output tokens" + (f" ≈ ${cost:.3f}" if cost is not None else "")
              + (f" | {extractor.failed_batches} batch(es) fell back to rules" if extractor.failed_batches else ""))
        print()

    if args.engine == "compare":
        compare(rules, claude)
    else:
        show(rules or claude)
    if rules:
        summary("rules", rules)
    if claude:
        summary("claude", claude)


if __name__ == "__main__":
    main()
