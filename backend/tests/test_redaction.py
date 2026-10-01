from redaction import redact


def test_account_number_removed():
    assert "123456789012" not in redact("NEFT TO A/C 123456789012 RAVI")


def test_upi_id_removed_but_vendor_kept():
    out = redact("UPI-SWIGGY-98765@ybl")
    assert "98765@ybl" not in out and "SWIGGY" in out


def test_email_card_pan_phone_removed():
    out = redact("ravi.kumar@example.com 4111 1111 1111 1111 ABCDE1234F +91 98765 43210")
    for secret in ("ravi.kumar", "4111", "ABCDE1234F", "98765"):
        assert secret not in out


def test_ordinary_text_unchanged():
    assert redact("AWS monthly bill invoice 101") == "AWS monthly bill invoice 101"
