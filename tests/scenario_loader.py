"""Load and validate the scenario dataset (tests/fixtures/scenarios/).

A scenario is a short story about the household: ordered steps, then the rows the
ledger must contain at the end. The files are engine-neutral data: today the bot's
functions replay them (tests/integration/test_scenarios.py); in Stage 4 the dbt
models will be checked against the same expected rows.

See tests/fixtures/scenarios/README.md for the file format.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

SCENARIO_DIR = Path(__file__).resolve().parent / "fixtures" / "scenarios"

STEP_KINDS = {"manual_entry", "statement_import", "stored_row"}
STEP_FIELDS = {
    "manual_entry": ({"user", "item", "amount", "account", "category", "date"}, {"comment", "expect"}),
    "statement_import": ({"user", "lines"}, {"expect_saved"}),
    "stored_row": ({"user", "account", "amount", "date", "description", "external_id"},
                   {"comment", "source_type", "status", "category"}),
}
LINE_FIELDS = ({"account", "amount", "date", "external_id", "description"}, {"comment", "source_type"})
# The ledger columns a scenario's expected rows are compared on. A missing field means null.
ROW_FIELDS = ({"user", "account", "amount", "date", "status", "source_type", "description"},
              {"external_id", "comment", "category"})
SCENARIO_FIELDS = ({"id", "description", "steps", "expected"}, {"known_issue"})


@dataclass(frozen=True)
class Household:
    users: dict[str, int]
    accounts: dict[str, dict[str, Any]]
    categories: dict[str, int]
    merchant_rules: dict[str, str]

    def account_key(self, account_id: int) -> str:
        return next(k for k, a in self.accounts.items() if a["id"] == account_id)

    def user_key(self, user_id: int) -> str:
        return next(k for k, uid in self.users.items() if uid == user_id)

    def category_key(self, category_id: int | None) -> str | None:
        if category_id is None:
            return None
        return next((k for k, cid in self.categories.items() if cid == category_id), f"<id {category_id}>")


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    steps: list[dict[str, Any]]
    expected: list[dict[str, Any]]
    known_issue: str | None
    path: Path


def _check_fields(where: str, data: Any, fields: tuple[set[str], set[str]]) -> None:
    required, optional = fields
    if not isinstance(data, dict):
        raise ValueError(f"{where}: expected a mapping, got {type(data).__name__}")
    missing = required - data.keys()
    unknown = data.keys() - required - optional
    if missing or unknown:
        raise ValueError(f"{where}: missing {sorted(missing)}, unknown {sorted(unknown)}")


def load_household(path: Path = SCENARIO_DIR / "household.yaml") -> Household:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    _check_fields(path.name, data, ({"users", "accounts", "categories", "merchant_rules"}, set()))
    ids = [a["id"] for a in data["accounts"].values()]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: duplicate account ids")
    household = Household(data["users"], data["accounts"], data["categories"], data["merchant_rules"])
    for key, account in household.accounts.items():
        _check_fields(f"{path.name} account {key}", account, ({"id", "name", "type"}, {"owner"}))
        if account.get("owner") is not None and account["owner"] not in household.users:
            raise ValueError(f"{path.name} account {key}: unknown owner {account['owner']!r}")
    for alias, category in household.merchant_rules.items():
        if category not in household.categories:
            raise ValueError(f"{path.name} merchant rule {alias!r}: unknown category {category!r}")
    return household


def _check_refs(where: str, data: dict[str, Any], household: Household) -> None:
    if "user" in data and data["user"] not in household.users:
        raise ValueError(f"{where}: unknown user {data['user']!r}")
    if "account" in data and data["account"] not in household.accounts:
        raise ValueError(f"{where}: unknown account {data['account']!r}")
    if data.get("category") is not None and data["category"] not in household.categories:
        raise ValueError(f"{where}: unknown category {data['category']!r}")
    if "date" in data and not isinstance(data["date"], date):
        raise ValueError(f"{where}: date must be YYYY-MM-DD")


def load_scenario(path: Path, household: Household) -> Scenario:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    _check_fields(path.name, data, SCENARIO_FIELDS)
    if data["id"] != path.stem:
        raise ValueError(f"{path.name}: id {data['id']!r} must match the file name")
    for n, step in enumerate(data["steps"], start=1):
        where = f"{path.name} step {n}"
        if not isinstance(step, dict) or len(step) != 1 or next(iter(step)) not in STEP_KINDS:
            raise ValueError(f"{where}: must be one of {sorted(STEP_KINDS)}")
        kind, body = next(iter(step.items()))
        _check_fields(where, body, STEP_FIELDS[kind])
        _check_refs(where, body, household)
        for m, line in enumerate(body.get("lines", []), start=1):
            _check_fields(f"{where} line {m}", line, LINE_FIELDS)
            _check_refs(f"{where} line {m}", line, household)
    for n, row in enumerate(data["expected"], start=1):
        _check_fields(f"{path.name} expected row {n}", row, ROW_FIELDS)
        _check_refs(f"{path.name} expected row {n}", row, household)
    return Scenario(data["id"], data["description"], data["steps"], data["expected"],
                    data.get("known_issue"), path)


def scenario_paths() -> list[Path]:
    return sorted(p for p in SCENARIO_DIR.glob("*.yaml") if p.name != "household.yaml")


def normalize_row(row: dict[str, Any]) -> tuple:
    """A comparable form of a ledger row: every compared field, missing ones as None."""
    fields = sorted(ROW_FIELDS[0] | ROW_FIELDS[1])
    values = {**dict.fromkeys(fields), **row}
    values["amount"] = round(float(values["amount"]), 2)
    return tuple((f, values[f]) for f in fields)
