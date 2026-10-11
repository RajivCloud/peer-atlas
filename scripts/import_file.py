"""Import a saved Discord paste into the database (same as the app's Import page).

Usage (from the project folder, with .venv active):
    python scripts/import_file.py data/paste_sample.txt                 # Claude (costs a little)
    python scripts/import_file.py data/paste_sample.txt --engine rules  # free
    python scripts/import_file.py data/paste_sample.txt --fresh         # redo extraction from scratch
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from core import db
from core.pipeline import import_text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--engine", choices=["claude", "rules"], default="claude")
    ap.add_argument("--fresh", action="store_true",
                    help="delete unreviewed peers and re-extract every message")
    args = ap.parse_args()

    db.init_db()
    if args.fresh:
        print(f"Removed {db.reset_extraction()} unreviewed peers; re-extracting all messages.")

    summary = import_text(Path(args.path).read_text(encoding="utf-8-sig"), engine=args.engine,
                          on_progress=lambda d, t: print(f"  Claude: {d}/{t} messages", flush=True))
    for key, value in summary.items():
        if key == "cost_usd":
            value = f"${value:.3f}" if value is not None else "free"
        print(f"{key.replace('_', ' '):>18}: {value}")
    print(f"\nDatabase: {db.DB_PATH}  ({len(db.list_peers())} peers total)")


if __name__ == "__main__":
    main()
