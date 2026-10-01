"""Generate a synthetic statement with planted anomalies. Run from the repo root:
    python backend/scripts/generate_sample_data.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)
rows = []
start = date(2026, 7, 1)


def add(day, description, amount):
    rows.append((start + timedelta(days=day), description, amount))


for month in range(3):
    base = month * 30
    add(base + 1, "NEFT-LANDLORD RENT", -25000)
    add(base + 3, "AWS INDIA BILL", -8000 - month * 210)
    add(base + 5, "NOTION LABS SUBSCRIPTION", -800)
    add(base + 7, "AIRTEL BROADBAND", -1178)
    add(base + 9, "BESCOM ELECTRICITY", -random.randint(2200, 3400))
    add(base + 12, "GITHUB INC", -1250)
    add(base + 14, "NEFT-ACME CORP INVOICE", random.randint(60, 90) * 1000)
    add(base + 20, "NEFT-ZENITH LTD INVOICE", random.randint(30, 50) * 1000)
    for day in random.sample(range(1, 29), 7):
        add(base + day, f"UBER INDIA {random.randint(1000, 9999)}", -random.randint(140, 480))
    for day in random.sample(range(1, 29), 6):
        add(base + day, f"SWIGGY ORDER {random.randint(1000, 9999)}", -random.randint(220, 780))
    for day in random.sample(range(1, 29), 3):
        add(base + day, f"AMAZON PAY INDIA {random.randint(1000, 9999)}", -random.randint(300, 4200))

# planted anomalies
add(3, "AWS INDIA BILL", -8000)  # exact duplicate of the first AWS bill
add(75, "UBER INDIA 7788", -48000)  # outlier
for i in range(5):  # velocity burst
    add(40, f"ZOMATO ORDER {5000 + i}", -random.randint(250, 600))
add(50, "NEFT TO A/C 123456789012 RAVI KUMAR", -15000)  # shows redaction

rows.sort()
out = Path(__file__).resolve().parents[2] / "sample_data" / "synthetic_transactions.csv"
with out.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "description", "amount"])
    for d, desc, amount in rows:
        w.writerow([d.isoformat(), desc, amount])
    w.writerow(["2026-09-30", "MALFORMED ROW EXAMPLE", "not-a-number"])  # shows partial-failure handling
print(f"wrote {len(rows) + 1} rows to {out}")
