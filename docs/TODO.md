# 📌 Current Tasks (TODO)

## 1. Batch Statement Loading (Debounce)
**Goal:** When sending multiple statement files (as a batch/album), the bot should group them and send a single summary report instead of spamming messages for each file.

- [x] Implement file collector (debounce) in document handler (`bot/handlers/document.py`) with a delay of ~1.5–2 seconds.
- [x] Group files and process them in a single pass.
- [x] Output a single neat summary report:
  - Total number of rows found
  - Number of new transactions added
  - Number of duplicates skipped
- [x] Output filenames and specific errors only for statements that encountered issues during processing.
- [x] Update and expand tests to verify batch imports.

---

## 2. Cash and Bit Wallet Tracking (Reconciliation)
**Goal:** Implement correct tracking of transit operations and cash expenditures.

- [x] Add aliases for the transit account (e.g., `bit`, `paybox`) to the `account_aliases` database table.
- [x] Rewrite logic for the "Cash Withdrawal" operation (category 43): it should now be an internal transfer from the card/bank account to the `Shared Cash` account instead of a simple expense.
- [x] Add basic balance tracking for the cash wallet.
- [x] Add correlation of Bit transfers from the transit account to personal accounts.

---

## 3. LLM Refactoring: Cleaning Up Dead Code, Voice Input, Analytics
**Superseded by #20.** Phases A and B (dead code removal, shared `save_expense_item()` service) were done. Instead of refactoring the remaining analytics (Phase C), the whole AI layer was removed: Gemini, voice input, NL→SQL analytics and `matplotlib`. Analytics will come back as part of the data platform (see `docs/ROADMAP.md`).

---

## 4. Import Fixes and Workflow
**Goal:** Fix the Isracard parser and simplify bulk transaction categorization.

- [x] Ignore pending transactions (without a voucher) during Isracard import to prevent data loss due to collisions.
- [x] Move alias update logic to the database level (PostgreSQL trigger on `UPDATE transactions`), eliminating duplicate Python code. *(Reverted in #8: the trigger duplicated the Python sync and was dropped in migration `0002`.)*
- [x] Create the `/uncategorized` command to list uncategorized transactions in Telegram with a convenient Inline keyboard.

---

## 5. Historical Cash Expense Import (Migration)
**Goal:** Develop and run a migration script to import historical cash expenses from the old bot version to populate analytics data.

- [x] Develop migration script `scripts/import_historical_cash.py` to read `bank_statements/legacy_cash_transactions_2023_2025.csv` (since removed; see `docs/LEGACY_SCRIPTS.md`).
- [x] Filter out transactions where `financing_source = 'Cash'`.
- [x] Map categories from the CSV file to the `seed_data.sql` structure (including parsing fuzzy categories like `Personal expenses` and `Other` using keywords in `purchase_name`).
- [x] Import transactions into the `budget.transactions` table under the account `account_id = 4` (Shared Cash).
- [x] Add duplicate prevention logic to the script for safe re-runs.
- [x] Reconcile the historical balance to zero with a single compensating transaction (top-up) on `account_id = 4` with category 43 (`Cash Withdrawal`).

---

## 6. Refactor Bit Wallet Tracking and Bit CSV Import
**Goal:** Implement full support for Bit CSV statements, establish exact reconciliation between Bit and Bank/Credit Card statements, and enhance category mapping by treating the `description + comment` composite string as the unique key for `item_aliases`.

**Context:**
- Bit acts both as a gateway for credit card payments and as a standalone wallet (transit account) holding a balance (`יתרה`).
- We can export Bit statements as CSV. The Bit CSV contains detailed transaction information (recipient/sender name) but no categorization.
- Bank/Credit Card statements only show an aggregated or generic description (e.g., `העברה ב BIT בנה"פ`).

### Phase A: Database and Categorization Refactoring
- [x] **A1.** Modify `bot/database.py` in `save_transactions_bulk` to adjust the reconciliation logic:
  - When matching Bank statement transactions, search for existing transactions where `amount` and `date` match AND `(status = 'pending' OR source_type = 'import_bit')`.
  - When updating a matched transaction, append the original description into the `comment` field (this is already implemented), but preserve the original `category_id`.
- [x] **A2.** Refactor the `item_aliases` structure and categorization logic in `bot/services/categorizer.py`:
  - When adding or updating an alias, the dictionary key should be the composite string `description + ' ' + comment` (or just `description` if `comment` is empty).
  - Modify `sync_category_by_alias` in `bot/database.py` to upsert using this composite key and update transactions matching both `description` and `comment`.

### Phase B: Bit CSV Parser Implementation
- [x] **B1.** Implement a new parser `bot/services/parsers/bit_parser.py` (or as a new function in `importer.py`):
  - Function `parse_bit_csv(file_path: str, account_id: int) -> List[Dict]`.
  - **Debit (`יתרה`):** Expense on `Transit (Bit/Paybox)` (ID: 5).
  - **Credit (`יתרה`):** Income on `Transit (Bit/Paybox)` (ID: 5).
  - **Withdrawal (`חשבון בנק`):** Internal Transfer from Transit (ID: 5) to Bank Account.
  - **Debit (`כרטיס אשראי`):** Expense on the respective Credit Card (passed via `account_id`).
  - Set `description` to the CSV `Description` column.
  - Set `comment` to the CSV `From/To` column.
  - Set `source_type` to `'import_bit'`.
  - Set `status` to `'confirmed'` for all Bit CSV transactions.
- [x] **B2.** Update `bot/handlers/imports.py` (or document handler) to detect Bit CSV files, map to the uploader's card, and process the file using the new parser.

### Phase C: Testing
- [x] **C1.** Write tests for the Bit CSV parser validating the different transaction types (Credit Card, Balance Debit/Credit, Withdrawal).
- [x] **C2.** Write tests for the reconciliation logic in `bot/database.py` to ensure that a transaction with `source_type = 'import_bit'` successfully receives the `external_id` from the Bank statement without duplicating.
