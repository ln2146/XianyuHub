import httpx
import respx

from tests.test_accounts import COOKIES, mock_probe
from tests.test_goofish_protocol import load


def ok(data):
    return httpx.Response(200, json={"ret": ["SUCCESS::ok"], "data": data})


def mock_anon():
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )


@respx.mock
async def test_selfcheck_anonymous_and_account(admin_client):
    mock_anon()
    respx.post(url__regex=r".*idlemtopsearch.*").mock(return_value=ok(load("search_response.json")["data"]))
    respx.post(url__regex=r".*idle\.pc\.detail.*").mock(return_value=ok(load("detail_response.json")["data"]))
    mock_probe()
    acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
    respx.post(url__regex=r".*pc\.login\.token.*").mock(return_value=ok({"accessToken": "tok"}))
    respx.post(url__regex=r".*xyh\.item\.list.*").mock(return_value=ok({"cardList": [], "nextPage": False}))
    respx.post(url__regex=r".*merchant\.sold\.get.*").mock(return_value=ok({"module": {"items": []}}))

    r = await admin_client.post("/api/v1/system/selfcheck", json={"keyword": "macbook", "account_id": acc["id"]})
    body = r.json()
    names = {c["name"]: c for c in body["checks"]}
    assert body["ok"], body
    assert names["search"]["coverage"]["标题"] == 1.0 and names["detail"]["ok"]
    assert names["im_token"]["ok"] and names["orders"]["coverage"] is None


@respx.mock
async def test_selfcheck_stops_on_risk(admin_client):
    mock_anon()
    respx.post(url__regex=r".*idlemtopsearch.*").mock(
        return_value=httpx.Response(200, json={"ret": ["FAIL_SYS_USER_VALIDATE"], "data": {}})
    )
    body = (await admin_client.post("/api/v1/system/selfcheck", json={})).json()
    assert not body["ok"]
    assert body["checks"][0]["detail"].startswith("风控") and body["checks"][1]["skipped"]


@respx.mock
async def test_selfcheck_flags_low_coverage(admin_client):
    mock_anon()
    rows = [{"data": {"item": {"main": {"exContent": {"itemId": str(i)}}}}} for i in range(5)]
    respx.post(url__regex=r".*idlemtopsearch.*").mock(return_value=ok({"resultList": rows}))
    respx.post(url__regex=r".*idle\.pc\.detail.*").mock(return_value=ok({"itemDO": {"itemId": 1}}))
    body = (await admin_client.post("/api/v1/system/selfcheck", json={})).json()
    assert not body["checks"][0]["ok"] and "解析器" in body["checks"][0]["detail"]
