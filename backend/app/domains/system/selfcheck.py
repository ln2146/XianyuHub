"""协议自检：用少量只读请求确认闲鱼接口与解析字段仍然有效。

字段覆盖率低通常意味着平台调整了接口结构，需要更新 app/goofish/parsers/ 中的解析器。
遇到风控信号立即停止后续检查，避免加重风控。
"""

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.db import session_factory
from app.core.deps import AdminUser
from app.domains.account.models import XyAccount
from app.domains.system.audit import record_audit
from app.goofish.dto import SearchQuery
from app.goofish.errors import RiskBlockedError, RiskControlError
from app.runtime import get_runtime

router = APIRouter(tags=["system"])

SEARCH_FIELDS = {
    "title": "标题",
    "price": "价格",
    "area": "地区",
    "seller_nick": "卖家昵称",
    "image_url": "主图",
    "publish_time": "发布时间",
    "want_cnt": "想要人数",
}
DETAIL_FIELDS = {
    "desc": "描述",
    "images": "图片",
    "browse_cnt": "浏览量",
    "want_cnt": "想要人数",
    "seller_id": "卖家 ID",
}
ORDER_FIELDS = {
    "order_id": "订单号",
    "status_text": "状态",
    "amount": "金额",
    "buyer_id": "买家 ID",
    "item_id": "商品 ID",
}


class SelfCheckIn(BaseModel):
    keyword: str = Field(default="iphone", min_length=1, max_length=40)
    account_id: int | None = None


class CheckResult(BaseModel):
    name: str
    title: str
    ok: bool = False
    skipped: bool = False
    ms: int = 0
    detail: str = ""
    coverage: dict[str, float] | None = None


def coverage(rows: list[Any], fields: dict[str, str]) -> dict[str, float]:
    if not rows:
        return {label: 0.0 for label in fields.values()}
    out = {}
    for attr, label in fields.items():
        filled = sum(1 for r in rows if getattr(r, attr, None) not in (None, "", [], 0))
        out[label] = round(filled / len(rows), 3)
    return out


async def run_selfcheck(keyword: str, account_id: int | None) -> tuple[bool, list[CheckResult]]:
    gw = get_runtime().gateway
    results: list[CheckResult] = []
    stopped = False
    ctx: dict[str, Any] = {}

    async def step(name: str, title: str, fn: Callable[[CheckResult], Awaitable[None]]) -> None:
        nonlocal stopped
        res = CheckResult(name=name, title=title)
        results.append(res)
        if stopped:
            res.skipped, res.detail = True, "前序检查触发风控，已停止"
            return
        start = time.monotonic()
        try:
            await fn(res)
        except (RiskControlError, RiskBlockedError) as e:
            stopped = True
            res.ok, res.detail = False, f"风控：{e}"
        except Exception as e:  # noqa: BLE001
            res.ok, res.detail = False, f"失败：{e}"
        res.ms = int((time.monotonic() - start) * 1000)

    async def search(res: CheckResult) -> None:
        page = await gw.search_items(SearchQuery(keyword=keyword, sort="default"))
        ctx["items"] = page.items
        res.coverage = coverage(page.items, SEARCH_FIELDS)
        res.ok = bool(page.items) and res.coverage["标题"] > 0.9 and res.coverage["价格"] > 0.8
        res.detail = f"返回 {len(page.items)} 个商品" + ("" if res.ok else "，字段缺失较多，解析器可能需要更新")

    async def detail(res: CheckResult) -> None:
        items = ctx.get("items") or []
        if not items:
            res.skipped, res.detail = True, "搜索无结果，跳过"
            return
        d = await gw.get_item_detail(items[0].item_id)
        res.coverage = coverage([d.item], DETAIL_FIELDS)
        res.coverage["芝麻信用"] = 1.0 if d.seller.zhima_level else 0.0
        res.ok = bool(d.item.title and d.item.images)
        res.detail = f"商品 {d.item.item_id}：{d.item.title[:30]}"

    await step("search", "匿名搜索（1 页）", search)
    await step("detail", "商品详情", detail)

    if account_id is not None:
        async with session_factory()() as s:
            acc = await s.get(XyAccount, account_id)
            unb, device_id = (acc.unb, acc.device_id) if acc else (None, None)

        async def login(res: CheckResult) -> None:
            if unb is None:
                raise ValueError("账号不存在")
            data = await gw.probe_login(account_id)
            res.ok, res.detail = True, f"登录态有效（{data.get('nick') or unb}）"

        async def im_token(res: CheckResult) -> None:
            token = await gw.get_im_token(account_id, device_id)
            res.ok, res.detail = bool(token), "已获取 IM accessToken"

        async def my_items(res: CheckResult) -> None:
            rows, more = await gw.list_my_items(account_id, unb)
            res.ok = True
            res.detail = f"第 1 页 {len(rows)} 个商品" + ("，还有更多" if more else "")

        async def orders(res: CheckResult) -> None:
            rows, _ = await gw.list_sold_orders(account_id)
            res.coverage = coverage(rows, ORDER_FIELDS) if rows else None
            res.ok = True
            res.detail = f"第 1 页 {len(rows)} 个订单" + ("" if rows else "（没有订单时无法检查字段）")

        await step("login", "登录态", login)
        await step("im_token", "IM 令牌", im_token)
        await step("my_items", "我的商品", my_items)
        await step("orders", "已售订单", orders)

    ok = all(r.ok or r.skipped for r in results) and not stopped
    return ok, results


@router.post("/system/selfcheck")
async def selfcheck(body: SelfCheckIn, admin: AdminUser) -> dict[str, Any]:
    started = datetime.now(UTC)
    ok, results = await run_selfcheck(body.keyword, body.account_id)
    await record_audit(
        "system.selfcheck",
        user_id=admin.id,
        actor_type="human",
        account_id=body.account_id,
        success=ok,
        detail={"failed": [r.name for r in results if not r.ok and not r.skipped]},
    )
    return {"ok": ok, "started_at": started, "checks": [r.model_dump() for r in results]}
