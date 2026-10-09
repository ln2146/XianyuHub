import httpx
import pytest

pytest.importorskip("mcp")

from app import mcp_server  # noqa: E402


async def test_mcp_tools_against_api(app, admin_client):
    r = await admin_client.post("/api/v1/auth/api-token", json={"name": "claude", "days": 30})
    token = r.json()["token"]
    mcp_server._client = mcp_server.XyhClient("http://test", token, transport=httpx.ASGITransport(app=app))
    try:
        tools = {t.name for t in await mcp_server.mcp.list_tools()}
        assert {"market_price", "radar_results", "preview_reply", "inbox", "orders", "overview"} <= tools
        assert all(t.annotations.read_only_hint for t in await mcp_server.mcp.list_tools())

        await admin_client.post(
            "/api/v1/buyer/tasks",
            json={
                "name": "M1",
                "keywords": ["m1"],
                "cron": "*/30 8-23 * * *",
                "decision_mode": "rule",
                "enabled": False,
            },
        )
        tasks = await mcp_server.monitor_tasks()
        assert tasks[0]["name"] == "M1"
        assert (await mcp_server.overview())["today"]["gmv"] == 0
        assert await mcp_server.inbox() == []
        with pytest.raises(RuntimeError, match="503"):
            await mcp_server.draft_monitor_task("想要一台 M1 Air")
    finally:
        await mcp_server._client.http.aclose()
        mcp_server._client = None
