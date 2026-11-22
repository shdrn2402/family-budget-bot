# Scenario dataset

Short, hand-written stories about a fake household. Each file says what happened, in
order, and which rows the ledger must contain at the end. The files are plain data, so the
same stories check the bot today (`tests/integration/test_scenarios.py`) and the dbt models
in Stage 4. Every value is made up.

- `household.yaml`: users, accounts, the reference categories used here, merchant rules.
- `<id>.yaml`: one scenario. The file name is its `id`.

## Scenario format

```yaml
id: pending_entry_confirmed_by_statement
description: What the story shows, in a sentence or two.
known_issue: Optional. Set when `expected` pins a known problem on purpose.
steps:            # replayed in order
  - manual_entry: {user, item, amount, account, category, date, comment?, expect?}
  - statement_import:
      user: alice                 # who uploads the statement
      lines:                      # parsed lines, in the shape the parsers return
        - {account, amount, date, external_id, description, comment?, source_type?}
      expect_saved: 1             # optional: rows the bot reports as saved
  - stored_row: {user, account, amount, date, description, external_id, comment?, source_type?, status?, category?}
expected:         # the whole ledger at the end, in any order
  - {user, account, amount, date, status, source_type, description, external_id?, comment?, category?}
```

- `user`, `account` and `category` are keys from `household.yaml`.
- `manual_entry.amount` is typed as positive; the sign comes from the category, as in the bot.
- `manual_entry.expect` is `pending`, `confirmed`, or `error:<code>`.
- `statement_import` runs what the bot does after parsing a file: merchant-rule categorization,
  offsetting rows for cash withdrawals and internal transfers, then reconciliation. File
  parsing itself is covered by `tests/fixtures/statements/`.
- `source_type` defaults to `import_xls`; `stored_row.status` defaults to `confirmed`.
- `stored_row` inserts a row as-is, like rows left by older code.
- In `expected`, a missing optional field means the column is empty (null).

When a known problem is fixed, change its `expected` (and drop `known_issue`) in the same PR,
so the fix shows up in review.
