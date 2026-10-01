import anthropic
import httpx
import pytest

from categorizer import categorize
from tests.fakes import FakeLLM

CATS = ["Software", "Travel", "Meals", "Rent"]
GOOD = '{"category": "Travel", "confidence": 0.95, "reasoning": "Ride-hailing"}'
LOW = '{"category": "Travel", "confidence": 0.4, "reasoning": "Unclear"}'
UNKNOWN = '{"category": "Pizza", "confidence": 0.9, "reasoning": "Food"}'
GARBAGE = "Sure! The category is Travel."


async def run(replies):
    fake = FakeLLM(replies)
    return await categorize(fake, "UBER INDIA 4471", 200, CATS), fake


async def test_good_reply():
    result, _ = await run([GOOD])
    assert (result.status, result.category, result.attempts) == ("categorized", "Travel", 1)


async def test_fenced_reply_is_accepted():
    result, _ = await run(["```json\n" + GOOD + "\n```"])
    assert result.status == "categorized"


async def test_invalid_then_valid_retries_once():
    result, fake = await run([GARBAGE, GOOD])
    assert (result.status, result.attempts) == ("categorized", 2)
    assert "invalid" in fake.calls[1]["messages"][-1]["content"]


@pytest.mark.parametrize("replies", [[GARBAGE, GARBAGE], [UNKNOWN, UNKNOWN]])
async def test_two_failures_fall_back_to_review(replies):
    result, _ = await run(replies)
    assert (result.status, result.category, result.attempts) == ("needs_review", None, 2)


async def test_low_confidence_goes_to_review():
    result, _ = await run([LOW])
    assert result.status == "needs_review" and result.category == "Travel"


async def test_transient_errors_are_retried():
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "http://x"))
    result, fake = await run([err, GOOD])
    assert result.status == "categorized" and len(fake.calls) == 2


async def test_persistent_outage_is_reported_not_raised():
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "http://x"))
    result, _ = await run([err, err, err])
    assert result.status == "needs_review" and result.error.startswith("LLM request failed")
