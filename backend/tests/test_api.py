import json

from tests.fakes import FakeLLM, text_response, tool_response

CSV = """date,description,amount
2026-09-01,UBER INDIA 1001,-200
2026-09-02,UBER INDIA 1002,-210
2026-09-03,UBER INDIA 1003,-190
2026-09-04,UBER INDIA 1004,-205
2026-09-05,UBER INDIA 1005,-195
2026-09-06,UBER INDIA 1006,-200
2026-09-07,UBER INDIA 1007,-50000
2026-09-08,NEFT TO ACCOUNT 123456789012 RAVI,-500
2026-09-09,BAD ROW,notanumber
2026-09-10,AWS BILL,-8420
2026-09-11,AWS BILL,-8420
2026-09-12,CUSTOMER ACME PAYMENT,25000
"""


async def signup(client, email="a@example.com"):
    r = await client.post("/auth/register", json={"email": email, "password": "correct-horse-1"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def upload(client, headers, content=CSV):
    return await client.post("/ingest/csv", files={"file": ("s.csv", content, "text/csv")}, headers=headers)


def category_fn(kwargs):
    system, prompt = kwargs["system"], kwargs["messages"][0]["content"]
    if "categorize" in system:
        if "UBER" in prompt:
            return '{"category": "Travel", "confidence": 0.95, "reasoning": "Ride-hailing"}'
        if "AWS" in prompt:
            return '{"category": "Software", "confidence": 0.9, "reasoning": "Cloud hosting"}'
        if "ACME" in prompt:
            return '{"category": "Sales", "confidence": 0.9, "reasoning": "Customer payment"}'
        return '{"category": "Meals", "confidence": 0.3, "reasoning": "Unclear"}'
    return '{"verdict": "confirm", "reasoning": "Looks odd"}'


def use_llm(fake):
    from llm import get_llm
    from main import app

    app.dependency_overrides[get_llm] = lambda: fake


async def test_auth_is_required(client):
    assert (await client.get("/transactions")).status_code == 401
    assert (await client.get("/transactions", headers={"Authorization": "Bearer nope"})).status_code == 401


async def test_login_and_wrong_password(client):
    await signup(client)
    ok = await client.post("/auth/login", data={"username": "a@example.com", "password": "correct-horse-1"})
    bad = await client.post("/auth/login", data={"username": "a@example.com", "password": "wrong-password"})
    assert ok.status_code == 200 and bad.status_code == 401


async def test_ui_is_served(client):
    r = await client.get("/app/")
    assert r.status_code == 200 and "Finance Copilot" in r.text


async def test_create_transaction_validates_balance_and_redacts(client):
    h = await signup(client)
    accounts = {a["name"]: a["id"] for a in (await client.get("/accounts", headers=h)).json()}
    body = {
        "txn_date": "2026-09-25", "description": "Transfer to 123456789012",
        "lines": [{"account_id": accounts["Travel"], "debit": 200}, {"account_id": accounts["Bank"], "credit": 200}],
    }
    ok = await client.post("/transactions", json=body, headers=h)
    assert ok.status_code == 201 and "123456789012" not in ok.json()["description"]

    body["lines"][1]["credit"] = 150
    assert (await client.post("/transactions", json=body, headers=h)).status_code == 422


async def test_csv_partial_failure_and_duplicate_upload(client):
    h = await signup(client)
    r = await upload(client, h)
    assert r.status_code == 201
    assert r.json()["inserted"] == 11
    assert r.json()["failed"] == [{"row": 10, "error": "unparseable amount 'notanumber'"}]
    assert (await upload(client, h)).status_code == 409
    assert (await upload(client, h, "date,amount\n2026-01-01,5")).status_code == 400


async def test_pipeline_categorizes_flags_and_never_leaks_account_numbers(client):
    h = await signup(client)
    await upload(client, h)
    fake = FakeLLM(fn=category_fn)
    use_llm(fake)

    summary = (await client.post("/pipeline/run", headers=h)).json()
    assert summary["processed"] == 11
    assert summary["categorized"] == 3  # first Uber, AWS and ACME each cost one LLM call
    assert summary["cache_hits"] == 7  # the other 6 Uber rides and 1 AWS bill reuse the cache
    assert summary["needs_review"] == 1  # the vague NEFT transfer (low confidence)
    assert len(fake.calls) == 4  # 4 distinct vendors, 4 calls for 11 transactions

    # security test: the account number never reaches the LLM payload or storage
    assert "123456789012" not in json.dumps(fake.calls, default=str)
    txns = (await client.get("/transactions", headers=h)).json()
    assert all("123456789012" not in t["description"] for t in txns)

    flags = (await client.get("/flags", headers=h)).json()
    assert {f["rule"] for f in flags} == {"outlier", "duplicate"}
    assert all(len(f["reason"]) > 20 for f in flags)

    runs = (await client.get("/agent-runs", headers=h)).json()
    assert {r["agent"] for r in runs} == {"categorizer"}
    assert all("123456789012" not in r["input_text"] for r in runs)

    status = (await client.get("/pipeline/status", headers=h)).json()
    assert status["transactions"] == {"pending": 0, "categorized": 10, "needs_review": 1}


async def test_manual_override_resolves_review_and_teaches_the_cache(client):
    h = await signup(client)
    await upload(client, h)
    use_llm(FakeLLM(fn=category_fn))
    await client.post("/pipeline/run", headers=h)

    review = (await client.get("/transactions?status=needs_review", headers=h)).json()
    accounts = {a["name"]: a for a in (await client.get("/accounts", headers=h)).json()}
    r = await client.patch(
        f"/transactions/{review[0]['id']}/category", json={"account_id": accounts["Rent"]["id"]}, headers=h
    )
    assert r.status_code == 200 and r.json()["status"] == "categorized"

    wrong_type = await client.patch(
        f"/transactions/{review[0]['id']}/category", json={"account_id": accounts["Sales"]["id"]}, headers=h
    )
    assert wrong_type.status_code == 400


async def test_pipeline_without_llm_sends_everything_to_review(client):
    h = await signup(client)
    await upload(client, h)
    summary = (await client.post("/pipeline/run", headers=h)).json()
    assert summary["categorized"] == 0 and summary["needs_review"] == 11


async def test_users_cannot_see_each_others_data(client):
    a = await signup(client, "a@example.com")
    b = await signup(client, "b@example.com")
    await upload(client, a)
    assert (await client.get("/transactions", headers=b)).json() == []
    txn_id = (await client.get("/transactions", headers=a)).json()[0]["id"]
    assert (await client.get(f"/transactions/{txn_id}", headers=b)).status_code == 404


async def test_query_agent_runs_scoped_sql_and_answers(client):
    a = await signup(client, "a@example.com")
    b = await signup(client, "b@example.com")
    await upload(client, a)
    use_llm(FakeLLM(fn=category_fn))
    await client.post("/pipeline/run", headers=a)

    count_sql = "SELECT COUNT(*) AS n FROM transactions"
    for headers, expected in ((a, 11), (b, 0)):
        fake = FakeLLM([tool_response(count_sql), "placeholder"])
        use_llm(fake)
        # second reply is built after the tool result comes back
        fake.replies[1] = text_response("done")
        r = await client.post("/query", json={"question": "How many transactions?"}, headers=headers)
        assert r.status_code == 200 and r.json()["refused"] is False
        tool_result = fake.calls[1]["messages"][-1]["content"][0]["content"]
        assert json.loads(tool_result) == [{"n": expected}]


async def test_query_agent_refuses_unsafe_sql_and_data_survives(client):
    h = await signup(client)
    await upload(client, h)
    fake = FakeLLM([tool_response("DROP TABLE transactions"), "I deleted everything."])
    use_llm(fake)
    r = await client.post("/query", json={"question": "Delete all my data"}, headers=h)
    assert r.json() == {"answer": "I couldn't answer that safely.", "sql": [], "refused": True}
    assert len((await client.get("/transactions", headers=h)).json()) == 11


async def test_query_without_llm_returns_503(client):
    h = await signup(client)
    assert (await client.post("/query", json={"question": "hello there"}, headers=h)).status_code == 503


async def test_rate_limit_on_query(client):
    h = await signup(client)
    use_llm(FakeLLM(fn=lambda kw: text_response("ok")))
    codes = [(await client.post("/query", json={"question": "hello there"}, headers=h)).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429
