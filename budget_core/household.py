"""The household file: accounts, merchant rules and merchant names that describe one household.

The real file is private and lives outside the repo; tests use a fake one
(tests/fixtures/household.example.yaml). scripts/load_household.py validates a file with
these models and writes it to the database (#70).
"""

import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AccountType = Literal["card", "cash", "transit"]
AccountRole = Literal["bank", "shared_cash", "transit", "default_card"]
MatchType = Literal["exact", "contains", "legacy"]


class _Entry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class User(_Entry):
    id: int  # Telegram user id
    name: str
    is_admin: bool = False


class Account(_Entry):
    id: int = Field(gt=0)
    # Required for a new account; for an existing one, a missing value keeps what's stored.
    name: dict[str, str] | None = Field(default=None, min_length=1)  # by language: {"en": ..., "ru": ...}
    type: AccountType | None = None
    owner: int | None = None  # a user id from `users` or already in the database
    card_last4: str | None = Field(default=None, pattern=r"^[0-9]{4}$")
    role: AccountRole | None = None
    # Words that name the account in typed entries ("coffee cash 5").
    aliases: tuple[str, ...] = ()

    @field_validator("aliases")
    @classmethod
    def _normalize_aliases(cls, aliases: tuple[str, ...]) -> tuple[str, ...]:
        # Typed entries look aliases up in lower case.
        return tuple(a.strip().lower() for a in aliases)


class MerchantRule(_Entry):
    pattern: str = Field(min_length=1)
    category: int  # a category id from the public category tree
    match_type: MatchType = "legacy"
    # Amount band on the absolute amount: above min, up to and including max.
    min_abs_amount: Decimal | None = Field(default=None, ge=0)
    max_abs_amount: Decimal | None = Field(default=None, ge=0)
    priority: int = Field(default=100, ge=0, le=32767)  # lower wins, then the older rule

    @model_validator(mode="after")
    def _band_is_ordered(self) -> "MerchantRule":
        if self.min_abs_amount is not None and self.max_abs_amount is not None \
                and self.min_abs_amount >= self.max_abs_amount:
            raise ValueError("min_abs_amount must be below max_abs_amount")
        return self


class MerchantName(_Entry):
    """Normalization: a cleaned statement name matching `pattern` becomes `canonical_name`.

    Names are tried in file order; the first match wins.
    """

    pattern: str = Field(min_length=1)  # a regular expression, searched in the cleaned name
    canonical_name: str = Field(min_length=1)

    @field_validator("pattern")
    @classmethod
    def _is_a_regex(cls, pattern: str) -> str:
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValueError(f"not a valid regular expression: {e}") from e
        return pattern


class Household(_Entry):
    users: tuple[User, ...] = ()
    accounts: tuple[Account, ...] = ()
    merchant_rules: tuple[MerchantRule, ...] = ()
    merchant_names: tuple[MerchantName, ...] = ()

    @model_validator(mode="after")
    def _unique_keys(self) -> "Household":
        def duplicates(values: list) -> list:
            seen, dup = set(), []
            for v in values:
                if v is not None and v in seen:
                    dup.append(v)
                seen.add(v)
            return dup

        checks = {
            "user id": [u.id for u in self.users],
            "account id": [a.id for a in self.accounts],
            "card_last4": [a.card_last4 for a in self.accounts],
            "account role": [a.role for a in self.accounts],
            "account alias": [alias for a in self.accounts for alias in a.aliases],
            "merchant rule (pattern and amount band)": [
                (r.pattern, r.min_abs_amount, r.max_abs_amount) for r in self.merchant_rules
            ],
            "merchant name pattern": [n.pattern for n in self.merchant_names],
        }
        # Counts, not values: the file is private and errors may be pasted elsewhere.
        problems = [f"{len(dup)} duplicate {what}" for what, values in checks.items() if (dup := duplicates(values))]
        if problems:
            raise ValueError("; ".join(problems))
        return self
