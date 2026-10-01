import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y")
MAX_ROWS = 5000
REQUIRED = {"date", "description", "amount"}


class CSVFormatError(ValueError):
    pass


@dataclass
class ParsedRow:
    row: int
    txn_date: date
    description: str
    amount: Decimal  # negative = money out


@dataclass
class RowError:
    row: int
    error: str


def _parse_date(raw: str) -> date:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{raw}'")


def parse_csv(content: bytes) -> tuple[list[ParsedRow], list[RowError]]:
    """Parse what we can. Bad rows are reported, never fatal."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CSVFormatError("file is not valid UTF-8 text")

    reader = csv.DictReader(io.StringIO(text))
    headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
    missing = REQUIRED - headers
    if missing:
        raise CSVFormatError(f"missing columns: {', '.join(sorted(missing))}")

    rows: list[ParsedRow] = []
    errors: list[RowError] = []
    for index, raw in enumerate(reader, start=2):
        if index - 1 > MAX_ROWS:
            raise CSVFormatError(f"more than {MAX_ROWS} rows")
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            description = row["description"]
            if not description:
                raise ValueError("empty description")
            try:
                amount = Decimal(row["amount"].replace(",", ""))
            except InvalidOperation:
                raise ValueError(f"unparseable amount '{row['amount']}'")
            if amount == 0:
                raise ValueError("amount is zero")
            rows.append(ParsedRow(index, _parse_date(row["date"]), description[:300], amount))
        except ValueError as e:
            errors.append(RowError(index, str(e)))
    return rows, errors
