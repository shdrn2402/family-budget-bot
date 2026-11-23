"""Read-only categorization audit (#64): replays the categorizer over stored statement rows.

Prints counts only: no merchant names, amounts, dates or ids, so the output can be shared.
The connection is read-only, so it can't change anything.

On the server (the bot container has the code and the database settings):

    docker compose exec -T budget_bot python scripts/audit_categorization.py

or, without deploying this file first:

    docker compose exec -T budget_bot python - < scripts/audit_categorization.py
"""
import sys
from collections import Counter
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path.cwd()))  # /app in the container, the repo root locally

from bot.config import Config  # noqa: E402
from budget_core.categorize import MerchantName, MerchantRule, clean_name, explain_category  # noqa: E402
from db.pool import CONNECTION_KWARGS  # noqa: E402

STATEMENT_ROWS = """
    SELECT description, amount, category_id
    FROM transactions
    WHERE source_type IN ('import_xls', 'import_bit')
      AND (external_id IS NULL OR external_id NOT LIKE '%\\_offset')
"""


STEPS = ("empty_name", "contains", "exact", "exact_raw", "partial", "none")
OUTCOMES = ("same as stored", "differs from stored", "stored uncategorized")


def rule_stats(rule_list: list[MerchantRule]) -> Counter:
    rules = {r.pattern: r.category_id for r in rule_list if r.match_type == "legacy"}
    stats: Counter = Counter(dict.fromkeys((
        "rules with digits", "rules of 1-3 characters", "rules all lower case (learned style)",
        "rule pairs nested with different categories",
    ), 0))
    stats["rules"] = len(rule_list)
    stats["legacy rules"] = len(rules)
    patterns = list(rules)
    for pattern in patterns:
        stats["rules with digits"] += any(ch.isdigit() for ch in pattern)
        stats["rules of 1-3 characters"] += len(pattern.strip()) <= 3
        stats["rules all lower case (learned style)"] += pattern == pattern.lower() and pattern != pattern.upper()
    # Pairs where one pattern is inside another (case-insensitive) but the categories differ:
    # a merchant matching the longer one usually matches the shorter one too (#65, #66).
    upper = [(p.upper(), rules[p]) for p in patterns]
    for i, (a, cat_a) in enumerate(upper):
        for b, cat_b in upper[i + 1:]:
            if cat_a != cat_b and (a in b or b in a):
                stats["rule pairs nested with different categories"] += 1
    return stats


def replay(rows: list[dict], rules: list[MerchantRule], names: list[MerchantName]) -> Counter:
    # Every metric is printed, zeros included, so a missing line never has to be guessed at.
    stats: Counter = Counter(dict.fromkeys((
        "statement rows",
        *(f"step: {step}" for step in STEPS),
        *(f"step: {step} / {outcome}" for step in STEPS for outcome in OUTCOMES),
        "partial: several rules, different categories (#65)",
        "partial: category changes when the rule order is reversed (#65)",
        "partial: won by name-inside-pattern (#66)",
        "contains rule overrides an exact rule for the same name (#67)",
    ), 0))
    reversed_rules = list(reversed(rules))
    exact = {r.pattern: r.category_id for r in reversed_rules if r.match_type in ("exact", "legacy")}
    for row in rows:
        stored = row["category_id"]
        match = explain_category(row["description"] or "", float(row["amount"]), rules, names)
        stats["statement rows"] += 1
        stats[f"step: {match.step}"] += 1
        if stored is None:
            outcome = "stored uncategorized"
        elif match.category_id == stored:
            outcome = "same as stored"
        else:
            outcome = "differs from stored"
        stats[f"step: {match.step} / {outcome}"] += 1

        if match.step == "partial":
            if len(set(match.partial_categories)) > 1:
                stats["partial: several rules, different categories (#65)"] += 1
            if explain_category(row["description"] or "", float(row["amount"]), reversed_rules, names).category_id \
                    != match.category_id:
                stats["partial: category changes when the rule order is reversed (#65)"] += 1
            if match.reverse_match:
                stats["partial: won by name-inside-pattern (#66)"] += 1
        if match.step == "contains":
            overridden = exact.get(clean_name(row["description"] or "", names))
            if overridden is not None and overridden != match.category_id:
                stats["contains rule overrides an exact rule for the same name (#67)"] += 1
    return stats


def report(conn: psycopg.Connection) -> str:
    """The audit as text, counts only."""
    rules = [MerchantRule(r["pattern"], r["category_id"], r["match_type"], r["min_abs_amount"], r["max_abs_amount"])
             for r in conn.execute(
                 "SELECT pattern, category_id, match_type, min_abs_amount, max_abs_amount "
                 "FROM app.merchant_rules ORDER BY priority, id"
             ).fetchall()]
    names = [MerchantName(r["pattern"], r["canonical_name"]) for r in conn.execute(
        "SELECT pattern, canonical_name FROM app.merchant_names ORDER BY priority, id"
    ).fetchall()]
    rows = conn.execute(STATEMENT_ROWS).fetchall()

    lines = [
        "Categorization audit (counts only)",
        "Rules are replayed in priority, id order. 'differs from stored' also counts categories changed by hand",
        "and rules learned after the import, so it is an upper bound on wrong categories.",
    ]
    for title, stats in (("Rules", rule_stats(rules)), ("Replay", replay(rows, rules, names))):
        lines.append(f"\n{title}")
        lines.extend(f"  {key}: {stats[key]}" for key in sorted(stats))
    return "\n".join(lines)


def main() -> None:
    with psycopg.connect(Config.db_conninfo(), **CONNECTION_KWARGS) as conn:
        conn.read_only = True
        print(report(conn))


if __name__ == "__main__":
    main()
