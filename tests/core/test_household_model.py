"""The household file format (budget_core.household, #70)."""
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from budget_core.household import Household

EXAMPLE = Path(__file__).resolve().parent.parent / "fixtures" / "household.example.yaml"


def _example() -> dict:
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def test_the_example_file_is_valid() -> None:
    household = Household.model_validate(_example())
    assert [a.role for a in household.accounts] == ["default_card", None, "bank", "shared_cash", "transit"]
    assert household.accounts[3].aliases == ("cash", "нал")
    assert [r.match_type for r in household.merchant_rules] == ["legacy", "exact", "contains", "contains"]


def test_aliases_are_stored_in_lower_case() -> None:
    data = _example()
    data["accounts"][0]["aliases"] = ["  AliceCard "]
    assert Household.model_validate(data).accounts[0].aliases == ("alicecard",)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["accounts"][1].update(card_last4="1111"), "1 duplicate card_last4"),
        (lambda d: d["accounts"][1].update(role="bank"), "1 duplicate account role"),
        (lambda d: d["accounts"][1].update(aliases=["bank"]), "1 duplicate account alias"),
        (lambda d: d["merchant_rules"].append({"pattern": "CAFE DEMO", "category": 18}),
         "1 duplicate merchant rule"),
        (lambda d: d["accounts"][0].update(card_last4="11a1"), "String should match pattern"),
        (lambda d: d["accounts"][0].update(role="savings"), "Input should be"),
        (lambda d: d["merchant_rules"][2].update(max_abs_amount=50), "min_abs_amount must be below"),
        (lambda d: d["merchant_names"][0].update(pattern="(unclosed"), "not a valid regular expression"),
        (lambda d: d["accounts"][0].update(colour="red"), "Extra inputs are not permitted"),
    ],
    ids=["card", "role", "alias", "rule", "digits", "role-name", "band", "regex", "unknown-field"],
)
def test_invalid_files_are_rejected(change, message: str) -> None:
    data = _example()
    change(data)
    with pytest.raises(ValidationError, match=message):
        Household.model_validate(data)


def test_duplicate_errors_name_the_field_not_the_value() -> None:
    """The real file is private; its values must not end up in error messages people paste."""
    data = _example()
    data["accounts"][1]["card_last4"] = "1111"
    with pytest.raises(ValidationError) as e:
        Household.model_validate(data)
    assert "1111" not in str(e.value.errors(include_input=False))
