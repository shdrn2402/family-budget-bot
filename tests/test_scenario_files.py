"""Structure checks for the scenario dataset (no database needed; the replay is in
tests/integration/test_scenarios.py)."""

from pathlib import Path

import pytest

from tests.scenario_loader import load_household, load_scenario, scenario_paths

HOUSEHOLD = load_household()


def test_there_are_scenarios() -> None:
    assert len(scenario_paths()) >= 20


@pytest.mark.parametrize("path", scenario_paths(), ids=lambda p: p.stem)
def test_scenario_file_is_valid(path: Path) -> None:
    scenario = load_scenario(path, HOUSEHOLD)
    assert scenario.steps, "a scenario needs at least one step"
    assert scenario.description.strip()
    if scenario.known_issue is not None:
        assert scenario.known_issue.strip()


def test_household_account_ids_match_the_ids_fixed_in_code() -> None:
    """Bank 3, shared cash 4 and transit 5 are still fixed in the parsers and the import step."""
    ids = {key: account["id"] for key, account in HOUSEHOLD.accounts.items()}
    assert (ids["family_bank"], ids["shared_cash"], ids["transit"]) == (3, 4, 5)


def test_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: bad\ndescription: x\nsteps:\n"
        "  - manual_entry: {user: alice, item: x, amount: 1, account: shared_cash, category: groceries,"
        " date: 2026-06-10, colour: red}\n"
        "expected: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown"):
        load_scenario(bad, HOUSEHOLD)


def test_loader_rejects_unknown_references(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: bad\ndescription: x\nsteps:\n"
        "  - manual_entry: {user: carol, item: x, amount: 1, account: shared_cash, category: groceries,"
        " date: 2026-06-10}\n"
        "expected: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown user"):
        load_scenario(bad, HOUSEHOLD)
