"""The read-only categorization audit script (#64) on a database with fake rows."""
import importlib.util
from pathlib import Path

import psycopg
from sqlalchemy.engine import URL

from db.pool import CONNECTION_KWARGS
from tests.integration.conftest import connect

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "audit_categorization.py"
spec = importlib.util.spec_from_file_location("audit_categorization", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

NAMES = ("SHOP ALPHA", "YELLOWSTONE CAFE", "BIG MARKET", "123456", "WOLT TLV 5678")


def test_report_counts_each_step_and_never_prints_merchant_names(seeded_url: URL) -> None:
    with connect(seeded_url) as conn:
        conn.execute("DELETE FROM app.merchant_rules")
        conn.execute(
            "INSERT INTO app.merchant_rules (pattern, category_id) VALUES "
            "('SHOP', 19), ('ALPHA', 17), ('YELLOWSTONE CAFE', 19), ('wolt tlv 1234', 19)"
        )
        conn.execute("INSERT INTO budget.users (id, name) VALUES (1, 'u')")
        rows = [
            ("SHOP ALPHA", -10, 19, "a"),          # partial, two categories, order decides
            ("YELLOWSTONE CAFE", -30, 19, "b"),    # amount rule (snacks) beats the exact rule
            ("BIG MARKET", -10, None, "c"),        # no rule
            ("123456", -10, None, "d"),            # empty after cleaning
            ("WOLT TLV 5678", -10, 19, "e"),       # learned rule, reverse direction
            ("BIG MARKET", 10, None, "c_offset"),  # offset rows are left out
        ]
        for description, amount, category, external_id in rows:
            conn.execute(
                "INSERT INTO budget.transactions (user_id, amount, description, date, category_id, "
                "external_id, source_type, status) VALUES (1, %s, %s, now(), %s, %s, 'import_xls', 'confirmed')",
                (amount, description, category, external_id),
            )
        conn.commit()

    with psycopg.connect(
        host=seeded_url.host, port=seeded_url.port, user=seeded_url.username,
        password=seeded_url.password, dbname=seeded_url.database, **CONNECTION_KWARGS,
    ) as conn:
        conn.read_only = True
        text = audit.report(conn)

    counts = {k.strip(): int(v) for k, v in (line.rsplit(":", 1) for line in text.splitlines() if line.startswith("  "))}
    assert counts["statement rows"] == 5
    assert counts["step: partial"] == 2
    assert counts["step: amount_rule"] == 1
    assert counts["step: none"] == 1
    assert counts["step: empty_name"] == 1
    assert counts["partial: several rules, different categories (#65)"] == 1
    assert counts["partial: category changes when the rule order is reversed (#65)"] == 1
    assert counts["partial: won by name-inside-pattern (#66)"] == 1
    assert counts["amount rule overrides an exact rule for the same name (#67)"] == 1
    assert counts["step: amount_rule / differs from stored"] == 1
    assert counts["rule pairs nested with different categories"] == 0
    for name in (*NAMES, "SHOP", "ALPHA", "wolt"):
        assert name.lower() not in text.lower()
