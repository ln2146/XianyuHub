"""闲鱼适配层门面：业务代码只通过 GoofishGateway 的能力方法与闲鱼交互。

每个方法都经过 RiskGuard（限流 / 熔断 / 互斥），底层默认走协议通道；
匿名搜索遇到风控且启用了浏览器通道时，自动降级到浏览器通道。
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx
from loguru import logger

from app.goofish.dto import ItemDetail, SearchPage, SearchQuery, SellerProfile
from app.goofish.errors import BizError, ChannelUnavailableError, NetworkError, RiskControlError
from app.goofish.guard.guard import ANON, RiskGuard
from app.goofish.guard.policy import Action
from app.goofish.parsers.common import dig
from app.goofish.parsers.market import (
    build_search_payload,
    parse_detail,
    parse_ratings,
    parse_search,
    parse_user_head,
    parse_user_items,
)
from app.goofish.parsers.trade import RemoteOrder, parse_order_detail, parse_sold_list
from app.goofish.protocol.cookies import dump_cookie_str
from app.goofish.protocol.mtop import DEFAULT_UA, MtopClient
from app.goofish.protocol.sign import IM_APP_KEY
from app.goofish.publish import PublishDraft, UploadedImage, build_category_request, build_publish_payload

UPLOAD_URL = "https://stream-upload.goofish.com/api/upload.api"


class SessionStore(Protocol):
    """账号凭证存取（由账号域实现，凭证加密落库）。"""

    async def load_cookies(self, account_id: int) -> dict[str, str]: ...

    async def save_cookies(self, account_id: int, cookies: dict[str, str]) -> None: ...

    async def get_proxy(self, account_id: int) -> str | None: ...


class SearchChannel(Protocol):
    async def search(self, query: SearchQuery) -> SearchPage: ...


def account_key(account_id: int | None) -> str:
    return ANON if account_id is None else f"acc:{account_id}"


# 网页版发布页的 spm：所在地接口据此返回附近地点
PUBLISH_SPM = "a21ybx.publish.0.0"


class GoofishGateway:
    def __init__(
        self,
        store: SessionStore,
        guard: RiskGuard,
        *,
        browser: SearchChannel | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        anon_proxy: str | None = None,
    ) -> None:
        self.store = store
        self.guard = guard
        self.browser = browser
        self._transport = transport
        self._anon = MtopClient(proxy=anon_proxy, transport=transport)
        self._clients: dict[int, MtopClient] = {}

    async def aclose(self) -> None:
        await self._anon.aclose()
        for c in self._clients.values():
            await c.aclose()
        self._clients.clear()

    async def invalidate(self, account_id: int) -> None:
        """账号 Cookie 被外部替换（重新扫码 / 导入）后调用。"""
        client = self._clients.pop(account_id, None)
        if client:
            await client.aclose()

    async def _client(self, account_id: int | None) -> MtopClient:
        if account_id is None:
            return self._anon
        client = self._clients.get(account_id)
        if client is None:
            cookies = await self.store.load_cookies(account_id)

            async def _persist(c: dict[str, str], aid: int = account_id) -> None:
                await self.store.save_cookies(aid, c)

            client = MtopClient(
                cookies,
                proxy=await self.store.get_proxy(account_id),
                transport=self._transport,
                on_cookies_updated=_persist,
            )
            self._clients[account_id] = client
        return client

    async def _call(
        self,
        account_id: int | None,
        action: Action,
        api: str,
        data: dict[str, Any],
        *,
        version: str = "1.0",
        extra_params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            client = await self._client(account_id)
            if account_id is None:
                await client.ensure_token()
            return await client.call(api, data, version=version, extra_params=extra_params, extra_headers=extra_headers)

        return await self.guard.run(account_key(account_id), action, _do)

    # ================================================================ 买家侧
    async def search_items(self, query: SearchQuery, account_id: int | None = None) -> SearchPage:
        try:
            data = await self._call(
                account_id, Action.SEARCH, "mtop.taobao.idlemtopsearch.pc.search", build_search_payload(query)
            )
            return parse_search(data, query.page)
        except RiskControlError:
            if self.browser is None:
                raise
            logger.warning("协议通道搜索触发风控，降级到浏览器通道 keyword={}", query.keyword)
            return await self.guard.run("browser", Action.SEARCH, lambda: self.browser.search(query))

    async def get_item_detail(self, item_id: str, account_id: int | None = None) -> ItemDetail:
        data = await self._call(account_id, Action.DETAIL, "mtop.taobao.idle.pc.detail", {"itemId": item_id})
        return parse_detail(data)

    async def get_seller_profile(
        self, seller_id: str, account_id: int | None = None, *, max_item_pages: int = 1, max_rate_pages: int = 2
    ) -> SellerProfile:
        head = await self._call(
            account_id, Action.SELLER_PROFILE, "mtop.idle.web.user.page.head", {"self": False, "userId": seller_id}
        )
        profile = parse_user_head(seller_id, head)
        for page in range(1, max_item_pages + 1):
            data = await self._call(
                account_id,
                Action.SELLER_PROFILE,
                "mtop.idle.web.xyh.item.list",
                {"needGroupInfo": False, "pageNumber": page, "userId": seller_id, "pageSize": 20},
            )
            rows, more = parse_user_items(data)
            profile.items.extend(rows)
            if not more:
                break
        for page in range(1, max_rate_pages + 1):
            data = await self._call(
                account_id,
                Action.SELLER_PROFILE,
                "mtop.idle.web.trade.rate.list",
                {"pageNumber": page, "pageSize": 20, "ratedUid": seller_id, "rateType": 0},
            )
            ratings, more = parse_ratings(data)
            profile.ratings.extend(ratings)
            if not more:
                break
        return profile

    # ================================================================ 账号 / IM
    async def probe_login(self, account_id: int) -> dict[str, Any]:
        """校验登录态（同时刷新 _m_h5_tk）。"""
        return await self._call(account_id, Action.USER_PROBE, "mtop.taobao.idlemessage.pc.loginuser.get", {})

    async def get_im_token(self, account_id: int, device_id: str) -> str:
        data = await self._call(
            account_id,
            Action.IM_TOKEN,
            "mtop.taobao.idlemessage.pc.login.token",
            {"appKey": IM_APP_KEY, "deviceId": device_id},
        )
        token = data.get("accessToken")
        if not token:
            raise BizError("未获取到 IM accessToken")
        return token

    async def cookie_header(self, account_id: int) -> str:
        return dump_cookie_str((await self._client(account_id)).cookies)

    # ================================================================ 卖家：商品
    async def list_my_items(self, account_id: int, user_id: str, page: int = 1) -> tuple[list[dict[str, Any]], bool]:
        data = await self._call(
            account_id,
            Action.MY_ITEMS,
            "mtop.idle.web.xyh.item.list",
            {"needGroupInfo": False, "pageNumber": page, "userId": user_id, "pageSize": 20},
        )
        return parse_user_items(data)

    async def upload_image(self, account_id: int, content: bytes, filename: str) -> UploadedImage:
        async def _do() -> UploadedImage:
            client = await self._client(account_id)
            async with httpx.AsyncClient(
                proxy=await self.store.get_proxy(account_id), transport=self._transport, timeout=60
            ) as http:
                resp = await http.post(
                    UPLOAD_URL,
                    params={"floderId": "0", "appkey": "xy_chat", "_input_charset": "utf-8"},
                    files={"file": (filename, content, "image/jpeg")},
                    headers={
                        "Cookie": dump_cookie_str(client.cookies),
                        "User-Agent": DEFAULT_UA,
                        "Origin": "https://www.goofish.com",
                        "Referer": "https://www.goofish.com/",
                    },
                )
            try:
                obj = resp.json().get("object") or {}
            except ValueError as e:
                raise NetworkError("图片上传返回非 JSON") from e
            if not obj.get("url"):
                raise BizError(f"图片上传失败：{resp.text[:200]}")
            w, _, h = str(obj.get("pix", "0x0")).partition("x")
            return UploadedImage(url=obj["url"], width=int(w or 0), height=int(h or 0))

        return await self.guard.run(account_key(account_id), Action.UPLOAD, _do)

    async def recommend_category(
        self, account_id: int, title: str, desc: str, images: list[UploadedImage]
    ) -> dict[str, Any]:
        return await self._call(
            account_id,
            Action.CATEGORY,
            "mtop.taobao.idle.kgraph.property.recommend",
            build_category_request(title, desc, images),
            version="2.0",
        )

    async def locations(self, account_id: int, longitude: float, latitude: float) -> dict[str, list[dict[str, Any]]]:
        """宝贝所在地候选：账号常用地址 + 坐标附近的地点（与网页版发布页同一接口）。
        坐标为高德 GCJ-02；接口要求带发布页的 spm 标识，否则只返回空对象。"""
        data = await self._call(
            account_id,
            Action.CATEGORY,
            "mtop.taobao.idle.local.poi.get",
            {"longitude": round(longitude, 6), "latitude": round(latitude, 6)},
            extra_params={"spm_cnt": PUBLISH_SPM},
            extra_headers={"eagleeye-userdata": f"spm-cnt={PUBLISH_SPM.split('.')[0]}"},
        )
        return {
            "common": list(data.get("commonAddresses") or []),
            "nearby": list(data.get("nearbyAddresses") or []),
        }

    async def default_address(self, account_id: int) -> dict[str, Any]:
        """未选择所在地时的兜底：账号在闲鱼 App 里的常用地址。"""
        common = (await self.locations(account_id, 121.4737, 31.2304))["common"]
        if not common:
            raise BizError("请先选择宝贝所在地（账号在闲鱼 App 里也没有常用地址）")
        return common[0]

    async def publish_item(self, account_id: int, draft: PublishDraft, location: dict[str, Any] | None = None) -> str:
        category = await self.recommend_category(account_id, draft.title, draft.desc, draft.images)
        address = location or await self.default_address(account_id)
        payload = build_publish_payload(draft, category, address)
        try:
            data = await self._call(account_id, Action.PUBLISH, "mtop.idle.pc.idleitem.publish", payload)
        except BizError as e:
            if "VERIFY_INFO" in str(e) or "未通过认证" in str(e):
                # 闲鱼要求发布前完成身份认证（实名 / 刷脸），只能在 App 里做
                raise BizError(
                    "账号还没通过闲鱼的发布认证：请在闲鱼 App 里点「卖闲置」发布一次，按提示完成实名或刷脸认证后再试",
                    ret=e.ret,
                    api=e.api,
                ) from e
            raise
        item_id = str(data.get("itemId") or dig(data, "item", "itemId", default="") or "")
        if not item_id:
            raise BizError(f"发布未返回商品 ID：{str(data)[:200]}")
        return item_id

    async def polish_item(self, account_id: int, item_id: str) -> None:
        await self._call(account_id, Action.POLISH, "mtop.taobao.idle.item.polish", {"itemId": item_id})

    async def offline_item(self, account_id: int, item_id: str) -> None:
        await self._call(
            account_id, Action.EDIT_ITEM, "mtop.alibaba.idle.seller.pc.item.batch.offline", {"itemIds": [item_id]}
        )

    # ================================================================ 卖家：订单
    async def list_sold_orders(
        self, account_id: int, page: int = 1, query_code: str = "ALL"
    ) -> tuple[list[RemoteOrder], bool]:
        data = await self._call(
            account_id,
            Action.ORDER_QUERY,
            "mtop.taobao.idle.trade.merchant.sold.get",
            {"pageNumber": page, "rowsPerPage": 30, "orderIds": "", "queryCode": query_code, "orderSearchParam": "{}"},
        )
        return parse_sold_list(data)

    async def get_order_detail(self, account_id: int, order_id: str) -> RemoteOrder:
        data = await self._call(account_id, Action.ORDER_QUERY, "mtop.idle.web.trade.order.detail", {"tid": order_id})
        return parse_order_detail(order_id, data)

    async def consign_virtual(self, account_id: int, order_id: str, trade_text: str = "") -> None:
        """虚拟发货（确认发货）。"""
        await self._call(
            account_id,
            Action.CONSIGN,
            "mtop.taobao.idle.logistic.consign.dummy",
            {"orderId": order_id, "tradeText": trade_text, "picList": [], "newUnconsign": True},
        )

    async def rate_order(self, account_id: int, order_id: str, content: str) -> None:
        await self._call(
            account_id,
            Action.RATE,
            "mtop.idle.rate.create",
            {"orderId": order_id, "rate": 1, "feedback": content, "picList": []},
            version="4.0",
        )


class BrowserSearchChannel:
    """浏览器通道：用 Playwright 打开搜索页并拦截 mtop 响应（不解析 DOM）。需安装 playwright 可选依赖。"""

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._pw: Any = None
        self._browser: Any = None

    async def _ensure(self) -> Any:
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as e:  # pragma: no cover - 可选依赖
                raise ChannelUnavailableError("未安装 playwright，无法使用浏览器通道") from e
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self.headless, args=["--disable-blink-features=AutomationControlled"]
            )
        return self._browser

    async def search(self, query: SearchQuery) -> SearchPage:  # pragma: no cover - 依赖真实浏览器
        from urllib.parse import quote

        browser = await self._ensure()
        context = await browser.new_context(locale="zh-CN", user_agent=DEFAULT_UA)
        await context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await context.new_page()
        try:
            async with page.expect_response(
                lambda r: "mtop.taobao.idlemtopsearch.pc.search" in r.url and r.request.method == "POST",
                timeout=30000,
            ) as resp_info:
                await page.goto(f"https://www.goofish.com/search?q={quote(query.keyword)}")
            if await page.query_selector("div.baxia-dialog-mask"):
                raise RiskControlError("浏览器通道出现滑块验证")
            payload = await (await resp_info.value).json()
            return parse_search(payload.get("data") or {}, 1)
        finally:
            await context.close()

    async def aclose(self) -> None:  # pragma: no cover
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()


GatewayFactory = Callable[[], Awaitable[GoofishGateway]]
