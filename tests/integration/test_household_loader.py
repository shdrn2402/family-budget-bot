"""Loading a household file into the database (db.household, scripts/load_household.py, #70)."""
import importlib.util
from pathlib import Path

import psycopg
import pytest
import yaml
from sqlalchemy.engine import URL

from budget_core.household import Household
from db import household, merchant_rules

ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE = ROOT / "tests" / "fixtures" / "household.example.yaml"

spec = importlib.util.spec_from_file_location("load_household", ROOT / "scripts" / "load_household.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def _example(**changes) -> Household:
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data.update(changes)
    return Household.model_validate(data)


async def _accounts(db: psycopg.AsyncConnection) -> list[tuple]:
    cur = await db.execute("SELECT id, type, owner_id, card_last4, role FROM accounts ORDER BY id")
    return [tuple(r.values()) for r in await cur.fetchall()]


async def test_loading_writes_accounts_aliases_rules_and_names(db: psycopg.AsyncConnection) -> None:
    counts = await household.apply(db, _example())
    await db.commit()

    assert counts["accounts updated"] == 5  # the seed's accounts 1-5, now described by the file
    assert await _accounts(db) == [
        (1, "card", 1001, "1111", "default_card"),
        (2, "card", 1002, "2222", None),
        (3, "card", None, None, "bank"),
        (4, "cash", None, None, "shared_cash"),
        (5, "transit", None, None, "transit"),
    ]
    cur = await db.execute("SELECT account_id FROM account_aliases WHERE name = 'нал'")
    assert (await cur.fetchone())["account_id"] == 4
    cur = await db.execute(
        "SELECT category_id, match_type, min_abs_amount, max_abs_amount, priority FROM app.merchant_rules "
        "WHERE pattern = 'FUEL DEMO' ORDER BY category_id"
    )
    assert [tuple(r.values()) for r in await cur.fetchall()] == [
        (17, "contains", None, 100, 10), (26, "contains", 100, None, 10)
    ]
    cur = await db.execute("SELECT pattern, canonical_name, priority FROM app.merchant_names ORDER BY priority")
    assert [tuple(r.values()) for r in await cur.fetchall()] == [
        ("^DEMO PAY", "DEMO PAY", 0), ("DEMO MART|DEMOMART", "DEMO MART", 1)
    ]


async def test_loading_twice_changes_nothing_the_second_time(db: psycopg.AsyncConnection) -> None:
    await household.apply(db, _example())
    rules_before = await merchant_rules.get_all(db)
    counts = await household.apply(db, _example())

    assert counts["merchant rules unchanged"] == 4 and counts["merchant rules added"] == 0
    assert counts["merchant names unchanged"] == 2 and counts["merchant names added"] == 0
    assert await merchant_rules.get_all(db) == rules_before


async def test_learned_rules_stay_and_merchant_names_follow_the_file(db: psycopg.AsyncConnection) -> None:
    await household.apply(db, _example())
    await merchant_rules.learn(db, "learned shop", 19, 1001)

    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["merchant_names"] = data["merchant_names"][1:]  # one name removed from the file
    counts = await household.apply(db, Household.model_validate(data))

    assert counts["merchant names removed"] == 1
    assert "learned shop" in await merchant_rules.get_all(db)


async def test_roles_and_card_digits_can_move_between_accounts(db: psycopg.AsyncConnection) -> None:
    await household.apply(db, _example())
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["accounts"][0].update(card_last4="2222", role=None)
    data["accounts"][1].update(card_last4="1111", role="default_card")
    await household.apply(db, Household.model_validate(data))

    assert (await _accounts(db))[:2] == [(1, "card", 1001, "2222", None), (2, "card", 1002, "1111", "default_card")]


async def test_the_bot_does_not_see_rules_it_cannot_apply_yet(db: psycopg.AsyncConnection) -> None:
    """Until part 2, contains/exact and amount-banded rules are invisible to the categorizer."""
    await household.apply(db, _example())
    rules = await merchant_rules.get_all(db)
    assert "CAFE DEMO" in rules  # legacy
    assert "FUEL DEMO" not in rules and "SUPER DEMO" not in rules
    assert await merchant_rules.find_category(db, "SUPER DEMO") is None


async def test_unknown_categories_are_refused(db: psycopg.AsyncConnection) -> None:
    with pytest.raises(ValueError, match=r"unknown category ids: \[999\]"):
        await household.apply(db, _example(merchant_rules=[{"pattern": "X", "category": 999}]))


def _conninfo(url: URL) -> str:
    return psycopg.conninfo.make_conninfo(
        host=url.host, port=url.port, user=url.username, password=url.password, dbname=url.database
    )


async def test_the_cli_dry_run_saves_nothing_and_prints_counts_only(seeded_url: URL) -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    output = await cli.load(_conninfo(seeded_url), cli.parse(text), dry_run=True)

    assert output.startswith("Dry run, nothing saved:")
    assert "merchant rules added: 4" in output
    for value in ("1111", "2222", "Alice", "CAFE DEMO", "DEMO MART", "нал"):
        assert value not in output
    async with await psycopg.AsyncConnection.connect(_conninfo(seeded_url)) as conn:
        assert await (await conn.execute("SELECT count(*) FROM app.merchant_names")).fetchone() == (0,)

    output = await cli.load(_conninfo(seeded_url), cli.parse(text), dry_run=False)
    assert output.startswith("Saved:")
    async with await psycopg.AsyncConnection.connect(_conninfo(seeded_url)) as conn:
        assert await (await conn.execute("SELECT count(*) FROM app.merchant_names")).fetchone() == (2,)


def test_the_cli_reports_invalid_files_without_their_values() -> None:
    with pytest.raises(SystemExit) as e:
        cli.parse("accounts:\n  - {id: 1, name: {en: X}, type: card, card_last4: '12a4'}\n")
    assert "accounts.0.card_last4" in str(e.value)
    assert "12a4" not in str(e.value)


async def test_existing_accounts_can_be_described_by_id_only(db: psycopg.AsyncConnection) -> None:
    """Production accounts already exist: a file with just id, card digits and role keeps their names."""
    cur = await db.execute("SELECT name FROM accounts WHERE id = 3")
    name_before = (await cur.fetchone())["name"]
    await household.apply(db, Household.model_validate({"accounts": [{"id": 3, "role": "bank"}]}))

    cur = await db.execute("SELECT name, type, role FROM accounts WHERE id = 3")
    row = await cur.fetchone()
    assert (row["name"], row["role"]) == (name_before, "bank")


async def test_a_new_account_needs_a_name_and_a_type(db: psycopg.AsyncConnection) -> None:
    with pytest.raises(ValueError, match=r"new accounts need a name and a type: ids \[77\]"):
        await household.apply(db, Household.model_validate({"accounts": [{"id": 77, "role": "bank"}]}))
