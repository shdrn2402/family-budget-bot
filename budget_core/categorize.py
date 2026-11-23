"""Statement-line categorization: clean the merchant name, then apply the household's rules.

Pure: the rules and names come from the database (app.merchant_rules, app.merchant_names) and
are passed in, already ordered by priority and id. Only bank-format knowledge lives here: Leumi
transaction prefixes, digits and punctuation, Isracard filler words and legal suffixes (#72).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

# Leumi lines that start with one of these are named by the prefix alone (ATM, cheque, ...).
LEUMI_PREFIXES = (
    "CHQ.WITHD", "BANKAT", "DISC CASPO", "LEUM CASPO",
    "MATRIX ATM'S", "SHIUN", "SNIFOMAT", "ATM CASH DEPOSIT",
    "IMMEDIATE TRANSFER", "ARREAR", "INTEREST ", "INT.M ",
    "CREDIT PLUS ", "LOAN PYMT ",
)
FILLER_WORDS = ("עסקה באילת", "תשלום")  # Isracard text that isn't part of the merchant name
LEGAL_SUFFIXES = ('בע"מ', "בעמ", "בע?מ", "בע")


@dataclass(frozen=True)
class MerchantRule:
    pattern: str
    category_id: int
    match_type: str = "legacy"  # 'exact', 'contains' or 'legacy' (today's two-way partial match)
    min_abs_amount: Decimal | None = None  # the absolute amount must be above this
    max_abs_amount: Decimal | None = None  # ... and at most this

    def fits(self, amount: float) -> bool:
        a = Decimal(str(abs(amount)))
        return (self.min_abs_amount is None or a > self.min_abs_amount) and \
            (self.max_abs_amount is None or a <= self.max_abs_amount)


@dataclass(frozen=True)
class MerchantName:
    pattern: str  # a regular expression, searched in the cleaned name
    canonical_name: str


@dataclass(frozen=True)
class CategoryMatch:
    """How a statement line got (or didn't get) its category."""

    category_id: int | None
    # 'empty_name', 'contains', 'exact', 'exact_raw', 'partial' or 'none'
    step: str
    # For 'partial': the categories of every partially matching rule, in rule order (the first wins).
    partial_categories: tuple[int, ...] = ()
    # For 'partial': True if the winning rule matched only because the name is inside its pattern.
    reverse_match: bool = False


def clean_leumi_name(name: str) -> str:
    """A Leumi line starting with a known prefix is named by the prefix; else the stripped name."""
    clean = str(name).strip()
    for prefix in LEUMI_PREFIXES:
        if clean.startswith(prefix):
            return prefix.strip()
    return clean if len(clean) > 1 else ""


def clean_name(name: str | None, names: Sequence[MerchantName] = ()) -> str:
    """The merchant name a statement line is matched on."""
    if name is None or (isinstance(name, float) and name != name) or not name:  # None, NaN or empty
        return ""

    leumi = clean_leumi_name(name)
    if leumi and leumi != str(name).strip():
        return leumi

    # Upper case; no digits, periods, dashes or asterisks; no filler words; single spaces.
    clean = re.sub(r"[\d\.\-\*]+", " ", str(name).upper())
    for word in FILLER_WORDS:
        clean = clean.replace(word, "")
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return ""

    # The household's normalization (brand spellings, branches...): the first match wins.
    for merchant in names:
        if re.search(merchant.pattern, clean):
            return merchant.canonical_name

    for suffix in LEGAL_SUFFIXES:
        if clean.endswith(" " + suffix):
            clean = clean[:-len(suffix) - 1].strip()
    return clean if len(clean) > 1 else ""


def explain_category(
    raw_name: str, amount: float, rules: Sequence[MerchantRule], names: Sequence[MerchantName] = ()
) -> CategoryMatch:
    """Categorize a statement line and say which step decided. `rules` are in priority, id order."""
    clean = clean_name(raw_name, names)
    if not clean:
        return CategoryMatch(None, "empty_name")

    # 1. 'contains' rules (e.g. amount bands for a fuel brand) come first.
    for rule in rules:
        if rule.match_type == "contains" and rule.pattern in clean and rule.fits(amount):
            return CategoryMatch(rule.category_id, "contains")

    lookup = [r for r in rules if r.match_type in ("exact", "legacy") and r.fits(amount)]

    # 2. Exact match on the cleaned name.
    for rule in lookup:
        if rule.pattern == clean:
            return CategoryMatch(rule.category_id, "exact")

    # 3. Exact match on the raw name, ignoring case (some rules were saved with punctuation).
    raw_upper = str(raw_name).strip().upper()
    for rule in lookup:
        if rule.pattern.upper() == raw_upper:
            return CategoryMatch(rule.category_id, "exact_raw")

    # 4. 'legacy' partial match, both ways (#66): the first matching rule wins.
    matches: list[tuple[int, bool]] = []
    for rule in lookup:
        if rule.match_type != "legacy":
            continue
        pattern = rule.pattern.upper()
        rule_in_name = pattern in clean or pattern in raw_upper
        if rule_in_name or clean in pattern or raw_upper in pattern:
            matches.append((rule.category_id, not rule_in_name))
    if matches:
        first_category, reverse = matches[0]
        return CategoryMatch(first_category, "partial", tuple(c for c, _ in matches), reverse)

    return CategoryMatch(None, "none")


def categorize(
    raw_name: str, amount: float, rules: Sequence[MerchantRule], names: Sequence[MerchantName] = ()
) -> int | None:
    """The category for a statement line, or None (see explain_category)."""
    return explain_category(raw_name, amount, rules, names).category_id
