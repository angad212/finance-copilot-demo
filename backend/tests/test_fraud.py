from datetime import date, timedelta
from decimal import Decimal

from agents.fraud import TxnView, detect


def txn(i, day, vendor, amount, category="Travel"):
    return TxnView(i, date(2026, 9, 1) + timedelta(days=day), vendor, Decimal(str(amount)), category)


def rules(flags):
    return {(f.transaction_id, f.rule) for f in flags}


def test_duplicate_charge_is_flagged():
    flags = detect([txn(1, 0, "AWS", 8420), txn(2, 2, "AWS", 8420)])
    assert rules(flags) == {(2, "duplicate")}


def test_same_amount_a_month_apart_is_not_a_duplicate():
    assert detect([txn(1, 0, "AWS", 8420), txn(2, 30, "AWS", 8420)]) == []


def test_planted_outlier_is_flagged():
    normal = [txn(i, i, "UBER INDIA", 200 + i * 5) for i in range(1, 8)]
    flags = detect(normal + [txn(99, 9, "UBER INDIA", 48000)])
    assert (99, "outlier") in rules(flags)
    assert all(f.transaction_id == 99 for f in flags)


def test_modest_variation_is_not_an_outlier():
    normal = [txn(i, i, "UBER INDIA", 200 + i * 5) for i in range(1, 8)]
    assert detect(normal + [txn(99, 9, "UBER INDIA", 232)]) == []


def test_velocity_flags_the_fourth_payment_onward():
    burst = [txn(i, 0, "SWIGGY", 300 + i) for i in range(1, 6)]
    assert rules(detect(burst)) == {(4, "velocity"), (5, "velocity")}


def test_every_flag_has_a_human_readable_reason():
    flags = detect([txn(1, 0, "AWS", 8420), txn(2, 1, "AWS", 8420)])
    assert all(len(f.reason) > 20 for f in flags)
