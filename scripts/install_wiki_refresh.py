"""Write a launchd calendar job for the deterministic Wiki refresh command."""

import argparse
import json
import plistlib
import sys
from datetime import date
from pathlib import Path


def job(
    *,
    repo: Path,
    python: Path,
    source: Path,
    logs: Path,
    anchor: date,
    axword: Path,
    seed: Path,
) -> dict:
    """Build an absolute command with a weekly Wednesday wakeup."""
    if anchor.weekday() != 2:
        raise ValueError("The fortnight anchor must be a Wednesday")
    return {
        "Label": "xyz.league-combat-calculator.wiki-refresh",
        "ProgramArguments": [
            str(python.absolute()),
            str(repo.absolute() / "scripts/patch_update.py"),
            "wiki-refresh",
            "--scryglass-root",
            str(source.absolute()),
            "--wiki-db",
            str(repo.absolute() / "data/wiki/league-wiki.sqlite3"),
            "--axword-source",
            str(axword.absolute()),
            "--seed-vault",
            str(seed.absolute()),
            "--scheduled",
            "--anchor-date",
            anchor.isoformat(),
        ],
        "WorkingDirectory": str(repo.absolute()),
        "EnvironmentVariables": {
            "SCRYGLASS_LEAGUE_WIKI_DB": str(
                repo.absolute() / "data/wiki/league-wiki.sqlite3"
            ),
            "LCC_WIKI_QUERY": str(
                repo.absolute()
                / "vendor/league-wiki-query/scripts/query_league_wiki.py"
            ),
        },
        "RunAtLoad": True,
        "StartCalendarInterval": {"Weekday": 3, "Hour": 9, "Minute": 0},
        "StandardOutPath": str(logs.absolute() / "wiki-refresh.stdout.log"),
        "StandardErrorPath": str(logs.absolute() / "wiki-refresh.stderr.log"),
        "ProcessType": "Background",
    }


def main() -> None:
    """Write the plist so an operator can load it with launchctl."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--scryglass-root", type=Path, required=True)
    parser.add_argument("--axword-source", type=Path, required=True)
    parser.add_argument("--seed-vault", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument(
        "--anchor-date", type=date.fromisoformat, default=date(2026, 9, 9)
    )
    args = parser.parse_args()
    for path in (
        args.python,
        args.axword_source,
        args.repo / "scripts/patch_update.py",
        args.repo / "vendor/league-wiki-query/scripts/query_league_wiki.py",
        args.scryglass_root / "lol_kills/knowledge/league_wiki_vault.py",
        args.scryglass_root / "lol_kills/knowledge/league_wiki_db.py",
        args.seed_vault / "latest.jsonl",
    ):
        if not path.is_file():
            parser.error(f"Required input is missing: {path}")
    value = job(
        repo=args.repo,
        python=args.python,
        source=args.scryglass_root,
        logs=args.logs,
        anchor=args.anchor_date,
        axword=args.axword_source,
        seed=args.seed_vault,
    )
    args.logs.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(plistlib.dumps(value))
    print(json.dumps({"plist": str(args.output.absolute()), "label": value["Label"]}))


if __name__ == "__main__":
    main()
