"""鱼塘管家 MCP Server：让 Claude 等 AI 助手通过 MCP 使用本系统的能力。

只开放只读与“试运行 / 草稿”类工具，不提供直接发送消息、发布商品、发货等写操作——
这些操作必须在管理台由人工确认。

运行（stdio）：
    XYH_BASE_URL=http://127.0.0.1:8000 XYH_TOKEN=<管理台生成的 API 令牌> \\
        uv run --extra mcp python -m app.mcp_server
"""

import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

mcp = MCPServer(
    name="xianyuhub",
    title="鱼塘管家",
    instructions=(
        "鱼塘管家是闲鱼买卖双端助手。可以查询同款行情、选品雷达推荐结果、收件箱会话、订单，"
        "并能试运行客服回复、根据一句话需求生成智能搜索草稿。所有对外写操作需要用户在管理台确认。"
    ),
)


class XyhClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, transport=None) -> None:  # noqa: ANN001
        base = (base_url or os.environ.get("XYH_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
        token = token or os.environ.get("XYH_TOKEN", "")
        self.http = httpx.AsyncClient(
            base_url=f"{base}/api/v1", headers={"Authorization": f"Bearer {token}"}, timeout=60, transport=transport
        )

    async def get(self, path: str, **params: Any) -> Any:
        resp = await self.http.get(path, params={k: v for k, v in params.items() if v is not None})
        return self._json(resp)

    async def post(self, path: str, body: dict[str, Any]) -> Any:
        return self._json(await self.http.post(path, json=body))

    @staticmethod
    def _json(resp: httpx.Response) -> Any:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except ValueError:
                detail = resp.text[:200]
            raise RuntimeError(f"鱼塘管家接口错误 {resp.status_code}：{detail}")
        return resp.json()


_client: XyhClient | None = None


def client() -> XyhClient:
    global _client
    if _client is None:
        _client = XyhClient()
    return _client


@mcp.tool(annotations=READ_ONLY)
async def market_price(keyword: str, my_price: float | None = None) -> dict[str, Any]:
    """查询闲鱼同款在售行情：样本数、建议的快速出手价 / 市场价 / 高价试水价，以及比 my_price 更便宜的竞品。"""
    return await client().get("/goods/market", keyword=keyword, my_price=my_price)


@mcp.tool(annotations=READ_ONLY)
async def radar_results(
    task_id: int | None = None, verdict: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """查看选品雷达的判定结果。verdict 可选 recommend / conditional / reject / all，默认只看推荐与有条件推荐。"""
    rows = await client().get("/buyer/results", task_id=task_id, verdict=verdict, limit=max(1, min(limit, 50)))
    return [
        {
            "title": r["item"]["title"],
            "price": r["item"]["price"],
            "area": r["item"]["area"],
            "link": r["item"]["link"],
            "verdict": r["verdict"],
            "deal": r["deal_label"],
            "reason": r["reason"],
            "risks": r["risk_tags"],
            "need_confirm": r["need_confirm"],
            "questions_for_seller": r["questions"],
        }
        for r in rows
    ]


@mcp.tool(annotations=READ_ONLY)
async def monitor_tasks() -> list[dict[str, Any]]:
    """列出选品雷达的智能搜索及最近一次运行情况。"""
    rows = await client().get("/buyer/tasks")
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "keywords": t["keywords"],
            "enabled": t["enabled"],
            "last_status": t["last_status"],
            "last_stats": t["last_stats"],
            "paused_reason": t["paused_reason"],
        }
        for t in rows
    ]


@mcp.tool(annotations=READ_ONLY)
async def draft_monitor_task(description: str) -> dict[str, Any]:
    """把一句话蹲货需求转换为智能搜索草稿（不会保存，需在管理台确认创建）。"""
    return await client().post("/buyer/tasks/generate", {"description": description})


@mcp.tool(annotations=READ_ONLY)
async def inbox(limit: int = 20) -> list[dict[str, Any]]:
    """列出最近的买家会话（含未读数、是否人工接管中）。"""
    rows = await client().get("/messages/conversations", limit=max(1, min(limit, 50)))
    return [
        {
            "conversation_id": c["id"],
            "account_id": c["account_id"],
            "buyer": c["peer_name"] or c["peer_id"],
            "item_id": c["item_id"],
            "last_message": c["last_message"],
            "unread": c["unread"],
            "in_takeover": c["in_takeover"],
        }
        for c in rows
    ]


@mcp.tool(annotations=READ_ONLY)
async def conversation_messages(conversation_id: int) -> list[dict[str, Any]]:
    """读取一个会话的消息记录。"""
    rows = await client().get(f"/messages/conversations/{conversation_id}/messages")
    return [
        {"direction": m["direction"], "source": m["source"], "text": m["text"], "at": m["created_at"]} for m in rows
    ]


@mcp.tool(annotations=READ_ONLY)
async def preview_reply(conversation_id: int, buyer_text: str) -> dict[str, Any]:
    """试运行客服流水线：给定买家消息，返回系统会如何回复（意图、议价报价、回复文本），不会真正发送。"""
    return await client().post("/messages/test-reply", {"conversation_id": conversation_id, "text": buyer_text})


@mcp.tool(annotations=READ_ONLY)
async def orders(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """查询订单。status 可选 paid / delivered / deliver_failed / manual / risk_hold 等。"""
    rows = await client().get("/orders", status=status, limit=max(1, min(limit, 50)))
    return [
        {
            "id": o["id"],
            "order_id": o["order_id"],
            "item": o["item_title"] or o["item_id"],
            "amount": o["amount"],
            "buyer": o["buyer_nick"] or o["buyer_id"],
            "status": o["status"],
            "fail_reason": o["fail_reason"],
        }
        for o in rows
    ]


@mcp.tool(annotations=READ_ONLY)
async def overview() -> dict[str, Any]:
    """今日概览：消息、发货、订单、GMV、选品推荐、账号健康与风控事件。"""
    d = await client().get("/dashboard")
    return {
        "today": d["today"],
        "accounts": d["accounts"],
        "pending_manual_orders": d["pending_manual_orders"],
        "risk_events": d["risk_events"][:5],
    }


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
