
# We will import these from the module once implemented
try:
    from bot.services.categorizer import clean_business_name, auto_categorize
except ImportError:
    # Stubs to allow the file to run and fail properly initially if module doesn't exist
    def clean_business_name(raw_name: str) -> str:
        raise NotImplementedError()
        
    def auto_categorize(raw_name: str, amount: float, db_aliases: dict[str, int]) -> int | None:
        raise NotImplementedError()


def test_clean_business_name_basic() -> None:
    """Test basic cleaning: remove digits, punctuation, and extra spaces."""
    assert clean_business_name("SOME BUSINESS 123") == "SOME BUSINESS"
    assert clean_business_name("TEST-STORE*NAME.") == "TEST STORE NAME"
    assert clean_business_name("עסקה באילת חנות") == "חנות"
    assert clean_business_name("תשלום ועד בית") == "ועד בית"

def test_clean_business_name_brands() -> None:
    """Test that big brands are normalized to their standard names."""
    assert clean_business_name("מקדולנדס סניף רעננה") == "מקדונלד'ס"
    assert clean_business_name("IKEA BEER SHEVA 4940") == "IKEA"
    assert clean_business_name("CARREFOUR 123") == "CARREFOUR"
    assert clean_business_name("פנגו מוביט") == "פנגו תחבורה ציבורית"

def test_clean_business_name_suffixes() -> None:
    """Test removal of legal suffixes."""
    assert clean_business_name("משה ודוד בע\"מ") == "משה ודוד"
    assert clean_business_name("חברה בעמ") == "חברה"

def test_auto_categorize_db_alias() -> None:
    """Test that standard DB aliases are found."""
    db_aliases = {
        "WOLT": 19,
        "סופר פארם": 17
    }
    # Direct match after clean. Assuming WOLT 123 cleans to WOLT
    # Wait, clean_business_name only normalizes big brands IF they are in the list.
    # If WOLT is not in the hardcoded list, WOLT 123 -> WOLT. 
    # Let's use a known brand for the test, or rely on digit stripping.
    assert auto_categorize("WOLT 123", -50.0, db_aliases) == 19
    assert auto_categorize("UNKNOWN STORE", -50.0, db_aliases) is None

def test_auto_categorize_yellow() -> None:
    """Test dynamic rules for YELLOW / אלונית / פז (Threshold 100)."""
    db_aliases: dict[str, int] = {}
    
    # Amount is negative (expense)
    assert auto_categorize("YELLOW MARKET 123", -20.0, db_aliases) == 17  # Snacks
    assert auto_categorize("YELLOW FUEL 123", -101.0, db_aliases) == 26  # Fuel
    
    # Other gas stations
    assert auto_categorize("אלונית", -150.0, db_aliases) == 26  # Fuel
    assert auto_categorize("פז רמת גן", -40.0, db_aliases) == 17  # Snacks
    
    # Positive amount (e.g. refund) - we should check absolute value
    assert auto_categorize("YELLOW", 120.0, db_aliases) == 26  # Fuel

def test_auto_categorize_dan_deal() -> None:
    """Test dynamic rules for Dan Deal (Threshold 50)."""
    db_aliases: dict[str, int] = {}
    
    assert auto_categorize("דן דיל", -30.0, db_aliases) == 17  # Snacks
    assert auto_categorize("דן דיל", -60.0, db_aliases) == 24  # Household


# --- Current behaviour pinned by the categorization audit (#64) ----------------------------
# These describe what the code does today, not what it should do. Each names its known issue.

FUEL, SNACKS, HOUSEHOLD, RESTAURANTS = 26, 17, 24, 19


def test_current_behaviour_partial_match_takes_the_first_rule_in_dict_order() -> None:
    """#65: two partially matching rules; the winner is whichever comes first in the dict, i.e. the
    unordered row order of merchant_rules.get_all(), which changes when a rule is learned again."""
    assert auto_categorize("SHOP ALPHA", -10.0, {"SHOP": 1, "ALPHA": 2}) == 1
    assert auto_categorize("SHOP ALPHA", -10.0, {"ALPHA": 2, "SHOP": 1}) == 2


def test_current_behaviour_partial_match_works_both_ways_with_no_minimum_length() -> None:
    """#66: a 2-letter rule matches any merchant containing it, and a short merchant name
    matches any rule that contains it."""
    assert auto_categorize("BIG MARKET", -10.0, {"AR": 6}) == 6
    assert auto_categorize("SHOP", -10.0, {"SHOPPING MALL": 3}) == 3


def test_current_behaviour_learned_rules_match_through_the_reverse_direction() -> None:
    """#66: the inline menu stores the raw description in lower case, digits included. A later line
    only matches because its cleaned name ('WOLT TLV') is inside that stored pattern."""
    learned = {"wolt tlv 1234": RESTAURANTS}
    assert clean_business_name("WOLT TLV 5678") == "WOLT TLV"
    assert auto_categorize("WOLT TLV 5678", -10.0, learned) == RESTAURANTS
    assert auto_categorize("TLV", -10.0, learned) == RESTAURANTS  # any name inside the pattern


def test_current_behaviour_amount_rules_beat_learned_rules_and_match_inside_words() -> None:
    """#67: the hard-coded amount rules run before merchant rules, match their keyword anywhere,
    and compare the absolute amount strictly."""
    corrected = {"פזגז": HOUSEHOLD}  # the user taught the bot this merchant's category
    assert auto_categorize("פזגז", -250.0, corrected) == FUEL  # 'פז' inside the name wins anyway
    assert auto_categorize("פזגז", -80.0, corrected) == SNACKS
    assert auto_categorize("YELLOWSTONE CAFE", -30.0, {"YELLOWSTONE CAFE": RESTAURANTS}) == SNACKS
    assert auto_categorize("YELLOW", -100.0, {}) == SNACKS  # strictly above 100 is fuel
    assert auto_categorize("YELLOW", -100.01, {}) == FUEL
    assert auto_categorize("דן דיל", -50.0, {}) == SNACKS
    assert auto_categorize("דן דיל", 60.0, {}) == HOUSEHOLD  # a refund counts by its absolute value


def test_current_behaviour_brand_names_match_anywhere_and_digits_are_dropped() -> None:
    """#68: brand normalization looks for the brand anywhere in the name, and every digit is removed."""
    assert clean_business_name("KFCX STORE") == "KFC"
    assert clean_business_name("AKSP COMPUTERS") == "KSP"
    assert clean_business_name("7-ELEVEN") == "ELEVEN"
    assert clean_business_name("123456") == ""
    assert auto_categorize("123456", -10.0, {"123456": 1}) is None  # an all-digit name is never categorized
