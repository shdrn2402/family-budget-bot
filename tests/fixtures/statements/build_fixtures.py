"""Build the fake statement files in this folder.

    uv run python tests/fixtures/statements/build_fixtures.py

Every value is made up (people, merchants, card 1111). The layouts reproduce
the real exports cell by cell: where tables start, header text, blank rows,
cell types (text vs number vs date), separators and footers, because that is
what the parsers depend on.

The Leumi .xls (legacy binary Excel) can't be written by current Python
libraries, so it is built as .xlsx and converted with headless LibreOffice,
using a fresh, empty profile so no personal document metadata ends up in it.

After a rebuild, refresh the expected outputs on purpose with
    UPDATE_GOLDENS=1 uv run pytest tests/test_statement_fixtures.py
and review the diff.
"""

import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

HERE = Path(__file__).resolve().parent
FIXED_TIME = datetime(2026, 1, 1)


def _workbook(sheet_title: str) -> Workbook:
    wb = Workbook()
    wb.active.title = sheet_title
    # Fixed metadata: no user name, no build time.
    wb.properties.creator = "fixture"
    wb.properties.lastModifiedBy = "fixture"
    wb.properties.created = FIXED_TIME
    wb.properties.modified = FIXED_TIME
    return wb


def _write_rows(ws, rows: list[list]) -> None:
    """Write rows from row 1; a [] row stays empty, None cells stay empty."""
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row, start=1):
            if value is not None:
                ws.cell(row=r, column=c, value=value)


# --- Isracard (.xlsx) ----------------------------------------------------------------

ISRACARD_SHEET = "פירוט עסקאות"
ISRACARD_HEADER = ["תאריך רכישה", "שם בית עסק", "סכום עסקה", "מטבע עסקה", "סכום חיוב", "מטבע חיוב", "מס' שובר", "פירוט נוסף"]
ISRACARD_HEADER_OUTSIDE = [*ISRACARD_HEADER, "חיוב בחשבון הבנק"]
ISRACARD_PENDING_HEADER = ISRACARD_HEADER[:4]

ISRACARD_FOOTER = [
    [],
    [],
    ["מידע כללי על החיוב"],
    ["סכום של 1 עסקאות בסך ₪12.00 טרם נקלט ויחויב בחודש הבא"],
    [],
    ["טקסט לדוגמה - תנאי השימוש בכרטיס, עמלות ומידע נוסף מופיעים באתר החברה.\nשורה שנייה של טקסט לדוגמה."],
]


def _isracard_title(month: str, total: str, billing: str) -> list[list]:
    return [
        [],
        [ISRACARD_SHEET, None, month],
        [],
        [],
        ["‫כרטיס לדוגמה‬ - 1111", None, None, None, None, None, None, total],
        ["על שם ישראל ישראלי", None, None, None, None, None, None, f"לחיוב ב-{billing}"],
        [],
        [],
    ]


def isracard_statement() -> list[list]:
    """A month with both regular tables: billing-date charges and charges outside it."""
    return [
        *_isracard_title("יוני 2026", "₪ 1,610.30", "15.06"),
        ["עסקאות למועד חיוב"],
        ISRACARD_HEADER,
        ["02.05.26", "סופר לדוגמה", 245.9, "₪", 245.9, "₪", "1000001"],
        ["03.05.26", "קפה הדגמה", 18, "₪", 18, "₪", "1000002"],
        ["05.05.26", "חברת סלולר לדוגמה", 49.9, "₪", 49.9, "₪", "1000003", "הוראת קבע"],
        # Installment: the transaction amount differs from this month's charge.
        ["07.05.26", "חנות רהיטים לדוגמה", 1200, "₪", 100, "₪", "1000004", "תשלום 3 מתוך 12"],
        ["09.05.26", "פארם לדוגמה", 64.5, "₪", 59.5, "₪", "1000005", "הנחה ₪5.00 "],
        ["12.05.26", 'דלק בע"מ לדוגמה', 300, "₪", 300, "₪", "1000006"],
        ["14.05.26", "מאפייה-שכונתית", 7.5, "₪", 7.5, "₪", "1000007"],
        ["20.05.26", "תשלום אחרון לדוגמה", 600, "₪", 50, "₪", "1000008", "תשלום 12 מתוך 12\nתשלום אחרון"],
        [None, 'סה"כ לחיוב החודש בכרטיס בש"ח', None, None, 830.8, "₪"],
        [],
        [],
        ["עסקאות בחיוב מחוץ למועד"],
        ISRACARD_HEADER_OUTSIDE,
        ["01.06.26", "STREAMING DEMO   AMSTERDAM", 39.9, "₪", 39.9, "₪", "2000001", "אתר חו\"ל\nהוראת קבע", "02.06.26"],
        # Foreign currency: charged in shekels.
        ["03.06.26", "DEMO STORE *ONLINE   LONDON", 20, "$", 74.6, "₪", "2000002", 'בוצע בחו"ל', "04.06.26"],
        ["05.06.26", "CLOUD.DEMO/BILL   DUBLIN", 665, "₪", 665, "₪", "2000003", 'אתר חו"ל', "06.06.26"],
        *ISRACARD_FOOTER,
    ]


def isracard_statement_with_pending() -> list[list]:
    """A month that starts with the pending-transactions table (4 columns, no voucher)."""
    return [
        *_isracard_title("יולי 2026", "₪ 412.00", "15.07"),
        [],
        [],
        [],
        ["עסקאות שטרם נקלטו"],
        ISRACARD_PENDING_HEADER,
        ["28.06.26", "מסעדה לדוגמה", 120, "₪"],
        ["29.06.26", "DEMO APP STORE", 9.99, "$"],
        [None, 'סה"כ עסקאות שטרם נקלטו', 156.6, "₪"],
        [],
        [],
        ["עסקאות למועד חיוב"],
        ISRACARD_HEADER,
        ["01.06.26", "סופר לדוגמה", 380, "₪", 380, "₪", "3000001"],
        ["02.06.26", "קפה הדגמה", 32, "₪", 32, "₪", "3000002"],
        [None, 'סה"כ לחיוב החודש בכרטיס בש"ח', None, None, 412, "₪"],
        *ISRACARD_FOOTER,
    ]


def build_isracard(name: str, rows: list[list]) -> None:
    wb = _workbook(ISRACARD_SHEET)
    _write_rows(wb.active, rows)
    wb.save(HERE / "isracard" / name)


# --- Leumi (.xls) --------------------------------------------------------------------

LEUMI_HEADER = [None, "Balance", "Value date", "Credit", "Debit", "Transaction", "Reference", "Code", "Date"]
BLANK = " "  # empty cells in the export are a single space, not blank


def _d(day: int) -> datetime:
    return datetime(2026, 6, day)


def leumi_rows() -> list[list]:
    def row(day: int, credit, debit, text: str, ref: int, code: int, balance=BLANK) -> list:
        return [None, balance, _d(day), credit, debit, text, ref, code, _d(day)]

    return [
        [],
        LEUMI_HEADER,
        [],
        [None, -1520.4, BLANK, BLANK, BLANK, "OPENING BALANCE", BLANK, BLANK, BLANK],
        row(1, 0.12, BLANK, "INTEREST CREDIT 0.10% 06/26", 100001, 469),
        row(1, BLANK, 0.35, "ACCOUNT FEE 0.10% 06/26", 100002, 470),
        row(2, BLANK, 650, "TRANSFER - 123456", 2000001, 175, balance=-2170.29),
        row(3, 12500, BLANK, "SALARY DEMO LTD", 30001, 120, balance=10329.71),
        # Card-company lines: the card statement already has the detail, so they're skipped.
        row(10, BLANK, 2310.75, "ISRACARD - 1111", 40001, 106),
        row(10, BLANK, 412, "ISRACARD - 1111", 40002, 106),
        row(12, BLANK, 99, "STANDING ORDER - 654321", 50001, 470, balance=7507.96),
        row(15, 300, BLANK, "BIT TRANSFER", 60001, 571),
        row(20, BLANK, 1250, "CASH WITHDRAWAL", 70001, 211, balance=6557.96),
    ]


def build_leumi(name: str) -> None:
    wb = _workbook("Activities")
    ws = wb.active
    _write_rows(ws, leumi_rows())
    for cells in ws.iter_rows():
        for cell in cells:
            if isinstance(cell.value, datetime):
                cell.number_format = "DD/MM/YYYY"

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        raise SystemExit("LibreOffice (soffice) is needed to build the .xls fixture")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        xlsx = tmp_path / (Path(name).stem + ".xlsx")
        wb.save(xlsx)
        profile = (tmp_path / "profile").as_uri()
        subprocess.run(
            [soffice, f"-env:UserInstallation={profile}", "--headless",
             "--convert-to", "xls", "--outdir", str(tmp_path), str(xlsx)],
            check=True, capture_output=True,
        )
        shutil.copy(tmp_path / name, HERE / "leumi" / name)


# --- Bit (.csv) ----------------------------------------------------------------------

BIT_HEADER = "Status, Description, Fee Amount, Amount, Payment Method, Credit/Debit, From/To, Date"
BIT_ROWS = [
    # Status, Description, Fee, Amount, Payment method, Credit/Debit, From/To, Date
    ("Done", "העברת כספים bit", "0", "150", "יתרה", "Credit", "ישראל ישראלי", "03.06.26"),
    ("Done", "תשלום ב-bit", "0", "80", "כרטיס אשראי", "Debit", "מסעדה לדוגמה", "05.06.26"),
    ("Done", "Перевод другу", "0", "45.5", "יתרה", "Debit", "Иван Петров", "07.06.26"),
    ("Done", "Withdrawal to bank account", "0", "300", "חשבון בנק", "Credit", "ישראל ישראלי", "10.06.26"),
    ("Done", "העברת כספים bit", "0", "500", "חשבון בנק", "Credit", "דנה כהן", "12.06.26"),
    ("Done", "Gift", "0", "100", "יתרה", "Credit", "דנה כהן", "14.06.26"),
    ("Done", "change", "0", "20", "חשבון בנק", "Credit", "ישראל ישראלי", "15.06.26"),
    # Two identical transfers on the same day.
    ("Done", "העברת כספים bit", "0", "25", "יתרה", "Debit", "משה לוי", "16.06.26"),
    ("Done", "העברת כספים bit", "0", "25", "יתרה", "Debit", "משה לוי", "16.06.26"),
    ("Expired", "העברת כספים bit", "0", "60", "יתרה", "Debit", "משה לוי", "18.06.26"),
    ("Failed", "תשלום ב-bit", "0", "70", "כרטיס אשראי", "Debit", "חנות לדוגמה", "19.06.26"),
    ("Done", "תשלום ב-bit", "0", "1200", "כרטיס אשראי", "Debit", "ועד בית לדוגמה", "20.06.26"),
]
BIT_FOOTER = [
    "",
    ",,,,,,1. The transaction details in the data files were generated via an automated interface "
    "and may contain spelling, formatting, or calculation errors. ",
    ",,,,,,2. Use discretion when downloading and/or sharing the data. ",
    ",,,,,,3. These files are not password-protected, and anyone with access can view them.",
]


def build_bit(name: str) -> None:
    # UTF-8 with BOM; ", " separators; data rows end with ", " but the header doesn't.
    lines = [BIT_HEADER, *(", ".join(r) + ", " for r in BIT_ROWS), *BIT_FOOTER]
    (HERE / "bit" / name).write_text("﻿" + "\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    build_isracard("1111_06_2026.xlsx", isracard_statement())
    build_isracard("1111_07_2026_with_pending.xlsx", isracard_statement_with_pending())
    build_leumi("FibiSave0000_06.xls")
    build_bit("bit_transactions_2026.csv")
    print("built:", *sorted(str(p.relative_to(HERE)) for p in HERE.rglob("*") if p.suffix in {".xlsx", ".xls", ".csv"}))


if __name__ == "__main__":
    main()
