"""/api/assets CRUD and /api/wealth/summary."""

HOUSE = {
    "kind": "real_estate",
    "name": "Casa Milano",
    "current_value": 350_000,
    "mortgage": {"principal": 200_000, "annual_rate_pct": 3, "years": 25,
                 "start_date": "2020-01-15", "balance_override": 150_000},
}


def test_assets_when_created_then_listed_with_server_id(client, auth_headers):
    saved = client.post("/api/assets", json=HOUSE, headers=auth_headers).json()
    assert len(saved["asset_id"]) == 32 and saved["updated_at"]
    listed = client.get("/api/assets", headers=auth_headers).json()
    assert [a["name"] for a in listed] == ["Casa Milano"]


def test_assets_when_updated_then_replaced_not_duplicated(client, auth_headers):
    saved = client.post("/api/assets", json=HOUSE, headers=auth_headers).json()
    client.post("/api/assets", json={**saved, "current_value": 360_000}, headers=auth_headers)
    listed = client.get("/api/assets", headers=auth_headers).json()
    assert len(listed) == 1 and listed[0]["current_value"] == 360_000


def test_assets_when_unknown_id_then_404(client, auth_headers):
    r = client.post("/api/assets", json={**HOUSE, "asset_id": "f" * 32}, headers=auth_headers)
    assert r.status_code == 404


def test_assets_when_invalid_then_422(client, auth_headers):
    bad = [{**HOUSE, "name": ""}, {**HOUSE, "current_value": -1}, {**HOUSE, "kind": "car"},
           {**HOUSE, "asset_id": "../x"}]
    for body in bad:
        assert client.post("/api/assets", json=body, headers=auth_headers).status_code == 422


def test_assets_when_deleted_then_gone(client, auth_headers):
    aid = client.post("/api/assets", json=HOUSE, headers=auth_headers).json()["asset_id"]
    client.delete(f"/api/assets/{aid}", headers=auth_headers)
    assert client.get("/api/assets", headers=auth_headers).json() == []


def test_assets_when_no_token_then_rejected(client):
    assert client.get("/api/assets").status_code in (401, 403)


def test_summary_when_portfolio_and_house_then_net_worth(client, auth_headers, fake_db):
    client.post("/api/assets", json=HOUSE, headers=auth_headers)
    pid = fake_db.save_portfolio_dynamo("mario", "ETF", {
        "holdings": [{"ticker": "SWDA", "amount": 40_000}], "liquidita": 10_000, "inputMode": "amount",
    })
    s = client.post("/api/wealth/summary", json={"portfolio_ids": [pid, pid]}, headers=auth_headers).json()
    assert s["total_assets"] == 400_000
    assert s["total_liabilities"] == 150_000
    assert s["net_worth"] == 250_000
    assert s["liquid_assets"] == 50_000
    assert len(s["portfolios"]) == 1


def test_summary_when_other_users_portfolio_then_404(client, auth_headers, fake_db):
    pid = fake_db.save_portfolio_dynamo("luigi", "Suo", {"holdings": []})
    r = client.post("/api/wealth/summary", json={"portfolio_ids": [pid]}, headers=auth_headers)
    assert r.status_code == 404


FUND = {"kind": "pension_fund", "name": "Cometa", "current_value": 20_000, "annual_contribution": 2_500,
        "birth_year": 1990, "tax_pct": 15, "pension_profile": "dynamic"}


def test_pension_endpoint_when_complete_then_simulation(client, auth_headers):
    aid = client.post("/api/assets", json=FUND, headers=auth_headers).json()["asset_id"]
    sim = client.get(f"/api/wealth/pension/{aid}", headers=auth_headers).json()
    assert sim["chosen"] == "dynamic" and len(sim["scenarios"]) == 3


def test_pension_endpoint_when_incomplete_then_400_with_reason(client, auth_headers):
    aid = client.post("/api/assets", json={**FUND, "tax_pct": None}, headers=auth_headers).json()["asset_id"]
    r = client.get(f"/api/wealth/pension/{aid}", headers=auth_headers)
    assert r.status_code == 400 and "tasse" in r.json()["detail"]


def test_pension_endpoint_when_unknown_then_404(client, auth_headers):
    assert client.get(f"/api/wealth/pension/{'0' * 32}", headers=auth_headers).status_code == 404


def test_policies_endpoint_when_mixed_assets_then_only_policies(client, auth_headers):
    client.post("/api/assets", json=FUND, headers=auth_headers)
    client.post("/api/assets", json={"kind": "life_insurance", "name": "Vita", "current_value": 5_000,
                                     "insurance_branch": "ramo_i"}, headers=auth_headers)
    body = client.get("/api/wealth/policies", headers=auth_headers).json()
    assert [p["name"] for p in body] == ["Vita"]
