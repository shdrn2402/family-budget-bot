"""Statement-line categorization (budget_core.categorize, #72), with fake rules and names.

The household's real rules and brand names are private data in the database.
"""
from decimal import Decimal

from budget_core.categorize import MerchantName, MerchantRule, categorize, clean_name, explain_category

FUEL, SNACKS, HOUSEHOLD, RESTAURANTS = 26, 17, 24, 19

NAMES = [  # tried in this order
    MerchantName("DEMO TRANSIT|RIDE.*DEMO", "DEMO TRANSIT"),
    MerchantName("^DEMO", "DEMO PARKING"),
    MerchantName("^GLOBALPAY", "GLOBALPAY"),
    MerchantName("MEGAMART|מגה מרט", "MEGAMART"),
    MerchantName("^חניון ", "חניון"),
]


def legacy(rules: dict[str, int]) -> list[MerchantRule]:
    return [MerchantRule(pattern, category) for pattern, category in rules.items()]


def band(pattern: str, category: int, low: str | None = None, high: str | None = None) -> MerchantRule:
    return MerchantRule(pattern, category, "contains",
                        Decimal(low) if low else None, Decimal(high) if high else None)


FUEL_RULES = [band("GASCO", FUEL, low="100"), band("GASCO", SNACKS, high="100"),
              band("BIGDEAL", HOUSEHOLD, low="50"), band("BIGDEAL", SNACKS, high="50")]


# --- Name cleaning (bank-format logic stays in code) ------------------------------------------

def test_digits_punctuation_and_filler_words_are_removed() -> None:
    assert clean_name("SOME BUSINESS 123") == "SOME BUSINESS"
    assert clean_name("TEST-STORE*NAME.") == "TEST STORE NAME"
    assert clean_name("עסקה באילת חנות") == "חנות"
    assert clean_name("תשלום ועד בית") == "ועד בית"


def test_legal_suffixes_are_removed() -> None:
    assert clean_name('משה ודוד בע"מ') == "משה ודוד"
    assert clean_name("חברה בעמ") == "חברה"


def test_leumi_lines_are_named_by_their_prefix() -> None:
    assert clean_name("INTEREST 2026") == "INTEREST"
    assert clean_name("IMMEDIATE TRANSFER 98765") == "IMMEDIATE TRANSFER"


def test_empty_and_one_letter_names_are_not_categorized() -> None:
    assert clean_name(None) == "" and clean_name("") == "" and clean_name("A") == ""
    assert explain_category("", -5.0, legacy({"": 1})).step == "empty_name"


# --- Name normalization (household data) ------------------------------------------------------

def test_names_are_normalized_by_the_first_matching_pattern() -> None:
    assert clean_name("MEGAMART BRANCH 4940", NAMES) == "MEGAMART"
    assert clean_name("מגה מרט רעננה", NAMES) == "MEGAMART"
    assert clean_name("DEMO TRANSIT 77", NAMES) == "DEMO TRANSIT"  # before the '^DEMO' pattern
    assert clean_name("DEMO GARAGE", NAMES) == "DEMO PARKING"
    assert clean_name("חניון עירוני", NAMES) == "חניון"
    assert clean_name("NOT A BRAND", NAMES) == "NOT A BRAND"


def test_a_normalized_name_keeps_its_legal_suffix_and_skips_suffix_removal() -> None:
    assert clean_name('GLOBALPAY בע"מ', NAMES) == "GLOBALPAY"


# --- Matching -----------------------------------------------------------------------------------

def test_exact_rules_and_unknown_names() -> None:
    rules = legacy({"WOLT": RESTAURANTS})
    assert categorize("WOLT 123", -50.0, rules) == RESTAURANTS
    assert categorize("UNKNOWN STORE", -50.0, rules) is None


def test_raw_name_matches_ignoring_case() -> None:
    assert explain_category("Some*Shop.", -5.0, legacy({"SOME*SHOP.": 5})).step == "exact_raw"


def test_amount_bands_split_one_merchant_by_amount() -> None:
    """Above the lower limit, up to and including the upper one, on the absolute amount."""
    assert categorize("GASCO MARKET 123", -20.0, FUEL_RULES) == SNACKS
    assert categorize("GASCO 123", -101.0, FUEL_RULES) == FUEL
    assert categorize("GASCO", -100.0, FUEL_RULES) == SNACKS
    assert categorize("GASCO", -100.01, FUEL_RULES) == FUEL
    assert categorize("GASCO", 120.0, FUEL_RULES) == FUEL  # a refund counts by its absolute value
    assert categorize("BIGDEAL", -50.0, FUEL_RULES) == SNACKS
    assert categorize("BIGDEAL", -60.0, FUEL_RULES) == HOUSEHOLD


def test_exact_match_type_never_matches_partially() -> None:
    rules = [MerchantRule("SHOP", 1, "exact")]
    assert categorize("SHOP", -5.0, rules) == 1
    assert categorize("SHOP ALPHA", -5.0, rules) is None


def test_partial_match_takes_the_first_rule_in_priority_order() -> None:
    """#65 fixed: rules come in priority, id order, so the result no longer depends on how the
    database happens to return rows. Here the list order stands for that order."""
    rules = legacy({"SHOP": 1, "ALPHA": 2})
    assert categorize("SHOP ALPHA", -10.0, rules) == 1
    assert explain_category("SHOP ALPHA", -10.0, rules).partial_categories == (1, 2)


# --- Current behaviour, pinned by the categorization audit (#64) ------------------------------

def test_current_behaviour_partial_match_works_both_ways_with_no_minimum_length() -> None:
    """#66: a 2-letter rule matches any merchant containing it, and a short merchant name
    matches any rule that contains it."""
    assert categorize("BIG MARKET", -10.0, legacy({"AR": 6})) == 6
    assert categorize("SHOP", -10.0, legacy({"SHOPPING MALL": 3})) == 3


def test_current_behaviour_learned_rules_match_through_the_reverse_direction() -> None:
    """#66: the inline menu stores the raw description in lower case, digits included. A later line
    only matches because its cleaned name ('WOLT TLV') is inside that stored pattern."""
    learned = legacy({"wolt tlv 1234": RESTAURANTS})
    assert clean_name("WOLT TLV 5678") == "WOLT TLV"
    assert categorize("WOLT TLV 5678", -10.0, learned) == RESTAURANTS
    assert categorize("TLV", -10.0, learned) == RESTAURANTS  # any name inside the pattern


def test_current_behaviour_contains_rules_beat_learned_rules_and_match_inside_words() -> None:
    """#67: 'contains' rules run before exact and learned rules and match inside other words."""
    rules = FUEL_RULES + legacy({"GASCOOKER": HOUSEHOLD})  # the user taught the bot this merchant
    assert categorize("GASCOOKER", -250.0, rules) == FUEL
    assert categorize("GASCOOKER", -80.0, rules) == SNACKS


def test_current_behaviour_brand_patterns_match_anywhere_and_digits_are_dropped() -> None:
    """#68: a normalization pattern without '^' matches anywhere in the name; every digit is removed."""
    assert clean_name("XMEGAMARTX STORE", NAMES) == "MEGAMART"
    assert clean_name("7-ELEVEN") == "ELEVEN"
    assert clean_name("123456") == ""
    assert categorize("123456", -10.0, legacy({"123456": 1})) is None  # an all-digit name is never categorized
