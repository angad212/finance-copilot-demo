"""Strip personal identifiers from free text before it is stored or sent to an LLM."""
import re

_REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(r"\b(?:\d{4}[ -]){3}\d{4}\b"),  # card numbers
    re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}\b"),  # 12-digit national IDs written in groups
    re.compile(r"[A-Za-z0-9._]+@[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*"),  # emails and UPI ids
    re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),  # PAN-style tax ids
    re.compile(r"\+91[ -]?\d{5}[ -]?\d{5}"),  # phone numbers with country code
    re.compile(r"\b\d{9,18}\b"),  # account numbers and other long digit runs
]


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text
