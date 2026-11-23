"""Load a household file into the database (#70). Prints counts only, never values.

The file is private and stays outside the repo. On the server:

    docker compose exec -T budget_bot python scripts/load_household.py --dry-run - < household.yaml
    docker compose exec -T budget_bot python scripts/load_household.py - < household.yaml

--dry-run validates the file and shows what would change, then rolls back.
"""
import argparse
import asyncio
import sys
from pathlib import Path

import psycopg
import yaml
from pydantic import ValidationError

sys.path.insert(0, str(Path.cwd()))  # /app in the container, the repo root locally

from bot.config import Config  # noqa: E402
from budget_core.household import Household  # noqa: E402
from db import household as household_repo  # noqa: E402
from db.pool import CONNECTION_KWARGS  # noqa: E402


def parse(text: str) -> Household:
    """Validate the file. Errors name the field, never the value."""
    try:
        return Household.model_validate(yaml.safe_load(text) or {})
    except ValidationError as e:
        lines = [f"  {'.'.join(str(p) for p in err['loc']) or '(file)'}: {err['msg']}"
                 for err in e.errors(include_input=False, include_url=False)]
        raise SystemExit("The household file is not valid:\n" + "\n".join(lines)) from None


async def load(conninfo: str, household: Household, *, dry_run: bool) -> str:
    async with await psycopg.AsyncConnection.connect(conninfo, **CONNECTION_KWARGS) as conn:
        counts = await household_repo.apply(conn, household)
        if dry_run:
            await conn.rollback()
        else:
            await conn.commit()
    title = "Dry run, nothing saved:" if dry_run else "Saved:"
    return "\n".join([title, *(f"  {key}: {counts[key]}" for key in sorted(counts))])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="the household YAML file, or - for stdin")
    parser.add_argument("--dry-run", action="store_true", help="validate and show changes, then roll back")
    args = parser.parse_args()
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    household = parse(text)
    try:
        print(asyncio.run(load(Config.db_conninfo(), household, dry_run=args.dry_run)))
    except psycopg.Error as e:
        # The primary message names the table and constraint; the detail (with values) is left out.
        primary, name = e.diag.message_primary or str(type(e).__name__), e.diag.constraint_name
        constraint = f" ({name})" if name and name not in primary else ""
        raise SystemExit(f"Nothing saved. Database error: {primary}{constraint}") from None
    except ValueError as e:
        raise SystemExit(f"Nothing saved. {e}") from None


if __name__ == "__main__":
    main()
