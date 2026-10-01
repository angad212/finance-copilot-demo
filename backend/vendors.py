import re


def normalize_vendor(description: str) -> str:
    """'UBER INDIA 4471' and 'Uber India 9981' both become 'UBER INDIA'."""
    s = description.upper().replace("[REDACTED]", " ")
    s = re.sub(r"[^A-Z ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:60] or "UNKNOWN"
