"""商品分析与商家分析：规则打分（无网络、可复现）+ 可选的大模型综合点评。

- 商品分析：市场价位置、价格走势、热度、信息完整度、异常低价。
- 商家分析：IP 属地与发货地是否一致 + 评价动态（时间分布、近期口碑走向、集中评价、负面关键词）
  + 在售商品同质化，综合判断个人玩家还是贩子 / 商家。
"""

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.goofish.dto import SellerProfile, SellerRating
from app.goofish.parsers.common import parse_ms
from app.intelligence.llm import LLMGateway, Tier
from app.intelligence.pricing import MarketStats, deal_label, deal_score, suspicious_low

# ---------------------------------------------------------------- 地区
# 省级行政区 → 常见地级市（用于把发货地“杭州”映射到 IP 属地“浙江”；未收录的城市按“无法比对”处理）
_PROVINCE_CITIES = {
    "北京": "北京",
    "天津": "天津",
    "上海": "上海",
    "重庆": "重庆",
    "河北": "石家庄 唐山 秦皇岛 邯郸 邢台 保定 张家口 承德 沧州 廊坊 衡水",
    "山西": "太原 大同 阳泉 长治 晋城 朔州 晋中 运城 忻州 临汾 吕梁",
    "内蒙古": "呼和浩特 包头 乌海 赤峰 通辽 鄂尔多斯 呼伦贝尔 巴彦淖尔 乌兰察布",
    "辽宁": "沈阳 大连 鞍山 抚顺 本溪 丹东 锦州 营口 阜新 辽阳 盘锦 铁岭 朝阳 葫芦岛",
    "吉林": "长春 吉林 四平 辽源 通化 白山 松原 白城 延边",
    "黑龙江": "哈尔滨 齐齐哈尔 鸡西 鹤岗 双鸭山 大庆 伊春 佳木斯 七台河 牡丹江 黑河 绥化",
    "江苏": "南京 无锡 徐州 常州 苏州 南通 连云港 淮安 盐城 扬州 镇江 泰州 宿迁 昆山 江阴 常熟 张家港",
    "浙江": "杭州 宁波 温州 嘉兴 湖州 绍兴 金华 衢州 舟山 台州 丽水 义乌 慈溪",
    "安徽": "合肥 芜湖 蚌埠 淮南 马鞍山 淮北 铜陵 安庆 黄山 滁州 阜阳 宿州 六安 亳州 池州 宣城",
    "福建": "福州 厦门 莆田 三明 泉州 漳州 南平 龙岩 宁德 晋江",
    "江西": "南昌 景德镇 萍乡 九江 新余 鹰潭 赣州 吉安 宜春 抚州 上饶",
    "山东": "济南 青岛 淄博 枣庄 东营 烟台 潍坊 济宁 泰安 威海 日照 临沂 德州 聊城 滨州 菏泽",
    "河南": "郑州 开封 洛阳 平顶山 安阳 鹤壁 新乡 焦作 濮阳 许昌 漯河 三门峡 南阳 商丘 信阳 周口 驻马店",
    "湖北": "武汉 黄石 十堰 宜昌 襄阳 鄂州 荆门 孝感 荆州 黄冈 咸宁 随州 恩施",
    "湖南": "长沙 株洲 湘潭 衡阳 邵阳 岳阳 常德 张家界 益阳 郴州 永州 怀化 娄底",
    "广东": "广州 韶关 深圳 珠海 汕头 佛山 江门 湛江 茂名 肇庆 惠州 梅州 汕尾 河源 阳江 清远 东莞 中山 潮州 揭阳 云浮",
    "广西": "南宁 柳州 桂林 梧州 北海 防城港 钦州 贵港 玉林 百色 贺州 河池 来宾 崇左",
    "海南": "海口 三亚 三沙 儋州",
    "四川": "成都 自贡 攀枝花 泸州 德阳 绵阳 广元 遂宁 内江 乐山 南充 眉山 宜宾 广安 达州 雅安 巴中 资阳",
    "贵州": "贵阳 六盘水 遵义 安顺 毕节 铜仁",
    "云南": "昆明 曲靖 玉溪 保山 昭通 丽江 普洱 临沧 大理 西双版纳",
    "西藏": "拉萨 日喀则 昌都 林芝 山南 那曲",
    "陕西": "西安 铜川 宝鸡 咸阳 渭南 延安 汉中 榆林 安康 商洛",
    "甘肃": "兰州 嘉峪关 金昌 白银 天水 武威 张掖 平凉 酒泉 庆阳 定西 陇南",
    "青海": "西宁 海东",
    "宁夏": "银川 石嘴山 吴忠 固原 中卫",
    "新疆": "乌鲁木齐 克拉玛依 吐鲁番 哈密 昌吉 伊犁 喀什 阿克苏 库尔勒 石河子",
    "香港": "香港",
    "澳门": "澳门",
    "台湾": "台湾 台北 高雄 台中",
}
_CITY_TO_PROVINCE = {c: p for p, cities in _PROVINCE_CITIES.items() for c in cities.split()}
_SUFFIX = re.compile(r"(省|市|特别行政区|壮族自治区|回族自治区|维吾尔自治区|自治区|地区|自治州)$")
_DOMESTIC = set(_PROVINCE_CITIES) - {"香港", "澳门", "台湾"}


def to_province(place: str | None) -> str | None:
    """'浙江省' / '杭州' / '杭州市' / '浙江 杭州' → '浙江'；无法识别返回 None。"""
    if not place:
        return None
    for token in re.split(r"[\s/·,，\-]+", place.strip()):
        name = _SUFFIX.sub("", token)
        if name in _PROVINCE_CITIES:
            return name
        if name in _CITY_TO_PROVINCE:
            return _CITY_TO_PROVINCE[name]
    return None


IpMatch = Literal["match", "mismatch", "overseas", "unknown"]


def compare_ip(ip_location: str, item_area: str) -> tuple[IpMatch, str]:
    ip = (ip_location or "").replace("IP属地", "").strip("：: ")
    if not ip:
        return "unknown", "未获取到 IP 属地"
    ip_prov = to_province(ip)
    if ip_prov is None or ip_prov not in _DOMESTIC:
        return "overseas", f"IP 属地为「{ip}」（非大陆），跨境交易售后与维权成本高"
    area_prov = to_province(item_area)
    if not item_area:
        return "unknown", f"IP 属地「{ip}」，商品未标注发货地"
    if area_prov is None:
        return "unknown", f"IP 属地「{ip}」，发货地「{item_area}」无法比对"
    if area_prov == ip_prov:
        return "match", f"IP 属地「{ip}」与发货地「{item_area}」一致"
    return "mismatch", f"IP 属地「{ip}」与发货地「{item_area}」不一致，可能异地代发、挂假定位或多地铺货"


# ---------------------------------------------------------------- 评价动态
NEGATIVE_WORDS = (
    "骗",
    "假货",
    "高仿",
    "不符",
    "翻新",
    "拆修",
    "维修过",
    "不发货",
    "没发货",
    "拒绝退",
    "退款",
    "态度差",
    "态度不好",
    "质量问题",
    "有问题",
    "坏了",
    "瑕疵",
    "失望",
    "垃圾",
)
POSITIVE_WORDS = (
    "靠谱",
    "诚信",
    "爽快",
    "描述一致",
    "如描述",
    "发货快",
    "秒发",
    "包装好",
    "推荐",
    "好卖家",
    "nice",
    "满意",
)
DEALER_WORDS = (
    "回收",
    "批发",
    "工作室",
    "店铺",
    "实体店",
    "货源",
    "专业",
    "全国包邮",
    "支持验机",
    "售后保障",
    "一手货",
    "批量",
)


_NEGATION = re.compile(r"(没|无|不|未|别|毫无)$")


def negative_hits(text: str) -> list[str]:
    """负面关键词命中；“没有问题”“无瑕疵”这类被否定的不算。"""
    hits = []
    for w in NEGATIVE_WORDS:
        start = text.find(w)
        while start != -1:
            if not _NEGATION.search(text[max(0, start - 2) : start]):
                hits.append(w)
                break
            start = text.find(w, start + 1)
    return hits


def _rating_time(r: SellerRating) -> datetime | None:
    raw = (r.created_at or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return parse_ms(raw)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw[: len(fmt) + 2].strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


class MonthBucket(BaseModel):
    month: str
    positive: int = 0
    neutral: int = 0
    negative: int = 0


class RatingEntry(BaseModel):
    content: str
    rate: int | None
    role: str
    created_at: datetime | None
    hits: list[str] = Field(default_factory=list)


class RatingDynamics(BaseModel):
    sampled: int = 0
    as_seller: int = 0  # 来自买家的评价（作为卖家收到的）
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    positive_rate: float | None = None
    recent_30d: int = 0
    recent_90d: int = 0
    recent_positive_rate: float | None = None  # 近 90 天
    earlier_positive_rate: float | None = None  # 90 天以前
    trend: Literal["up", "down", "stable", "unknown"] = "unknown"
    last_rated_at: datetime | None = None
    burst: bool = False
    burst_note: str = ""
    monthly: list[MonthBucket] = Field(default_factory=list)
    negative_hits: list[tuple[str, int]] = Field(default_factory=list)
    positive_hits: list[tuple[str, int]] = Field(default_factory=list)
    negatives: list[RatingEntry] = Field(default_factory=list)
    recent: list[RatingEntry] = Field(default_factory=list)


def _pos_rate(rs: list[SellerRating]) -> float | None:
    rated = [r for r in rs if r.rate is not None]
    return round(sum(1 for r in rated if r.rate == 1) / len(rated), 3) if rated else None


def rating_dynamics(ratings: list[SellerRating], now: datetime | None = None) -> RatingDynamics:
    now = now or datetime.now(UTC)
    # 作为卖家收到的评价才反映卖货口碑；接口未区分角色时全部计入
    seller_side = [r for r in ratings if "买家" in r.role] or [r for r in ratings if "卖家" not in r.role]
    d = RatingDynamics(sampled=len(ratings), as_seller=len(seller_side))
    if not seller_side:
        return d
    d.positive = sum(1 for r in seller_side if r.rate == 1)
    d.neutral = sum(1 for r in seller_side if r.rate == 0)
    d.negative = sum(1 for r in seller_side if r.rate is not None and r.rate < 0)
    d.positive_rate = _pos_rate(seller_side)

    timed = sorted(((t, r) for r in seller_side if (t := _rating_time(r))), key=lambda x: x[0], reverse=True)
    recent90 = [r for t, r in timed if now - t <= timedelta(days=90)]
    earlier = [r for t, r in timed if now - t > timedelta(days=90)]
    d.recent_30d = sum(1 for t, _ in timed if now - t <= timedelta(days=30))
    d.recent_90d = len(recent90)
    d.recent_positive_rate = _pos_rate(recent90)
    d.earlier_positive_rate = _pos_rate(earlier)
    if d.recent_positive_rate is not None and d.earlier_positive_rate is not None and len(recent90) >= 3:
        delta = d.recent_positive_rate - d.earlier_positive_rate
        d.trend = "down" if delta <= -0.1 else "up" if delta >= 0.1 else "stable"
    elif timed:
        d.trend = "stable"
    if timed:
        d.last_rated_at = timed[0][0]

    # 集中评价：任意 7 天窗口内的评价数占样本过半且 ≥ 6 条 → 刷评或批量出货
    times = [t for t, _ in timed]
    peak = max((sum(1 for u in times if timedelta(0) <= t - u <= timedelta(days=7)) for t in times), default=0)
    if peak >= 6 and peak >= len(times) * 0.5:
        d.burst = True
        d.burst_note = f"{peak} 条评价集中在 7 天内出现"

    buckets: dict[str, MonthBucket] = {}
    for t, r in timed:
        b = buckets.setdefault(t.strftime("%Y-%m"), MonthBucket(month=t.strftime("%Y-%m")))
        if r.rate == 1:
            b.positive += 1
        elif r.rate == 0:
            b.neutral += 1
        elif r.rate is not None:
            b.negative += 1
    if buckets:
        # 最近 12 个月逐月补齐（没有评价的月份为 0），沉寂期才能在图上看出来
        last = max(buckets)
        y, m = int(last[:4]), int(last[5:])
        months = []
        for _ in range(12):
            months.append(f"{y:04d}-{m:02d}")
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        first = min(buckets)
        d.monthly = [buckets.get(k) or MonthBucket(month=k) for k in reversed(months) if k >= first]

    neg_counter: Counter[str] = Counter()
    pos_counter: Counter[str] = Counter()
    when = {id(r): t for t, r in timed}

    def entry(r: SellerRating, hits: list[str]) -> RatingEntry:
        return RatingEntry(content=r.content[:200], rate=r.rate, role=r.role, created_at=when.get(id(r)), hits=hits)

    for r in seller_side:
        text = r.content or ""
        neg = negative_hits(text)
        neg_counter.update(neg)
        pos_counter.update(w for w in POSITIVE_WORDS if w in text)
        if (r.rate is not None and r.rate < 1) or neg:
            d.negatives.append(entry(r, neg))
    d.negative_hits = neg_counter.most_common(8)
    d.positive_hits = pos_counter.most_common(8)
    d.negatives = d.negatives[:10]
    ordered = [r for _, r in timed] + [r for r in seller_side if id(r) not in when]
    d.recent = [entry(r, negative_hits(r.content)) for r in ordered if r.content][:12]
    return d


# ---------------------------------------------------------------- 在售商品
def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[\s\W_]+", "", text.lower())
    return {t[i : i + 2] for i in range(len(t) - 1)}


def title_homogeneity(titles: list[str]) -> float:
    """在售标题两两 bigram Jaccard 的均值：贩子 / 商家批量铺同款时明显偏高。"""
    grams = [g for g in (_bigrams(t) for t in titles[:20]) if g]
    if len(grams) < 3:
        return 0.0
    total, pairs = 0.0, 0
    for i in range(len(grams)):
        for j in range(i + 1, len(grams)):
            total += len(grams[i] & grams[j]) / len(grams[i] | grams[j])
            pairs += 1
    return round(total / pairs, 3)


# ---------------------------------------------------------------- 商家分析
class SellerAnalysis(BaseModel):
    seller_id: str
    nick: str = ""
    avatar: str = ""
    introduction: str = ""
    ip_location: str = ""
    item_area: str = ""
    ip_match: IpMatch = "unknown"
    ip_note: str = ""
    zhima: str = ""
    reg_days: int | None = None
    sold_cnt: int | None = None
    seller_credit: str = ""
    item_cnt: int | None = None
    rate_cnt: int | None = None
    on_sale_sampled: int = 0
    sold_sampled: int = 0
    homogeneity: float = 0.0
    dealer_words: list[str] = Field(default_factory=list)
    ratings: RatingDynamics = Field(default_factory=RatingDynamics)
    seller_type: Literal["personal", "dealer", "unknown"] = "unknown"
    type_reasons: list[str] = Field(default_factory=list)
    score: int = 0
    level: str = ""
    highlights: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    fetched_at: datetime | None = None


_ZHIMA_BONUS = {"极好": 10, "优秀": 6, "良好": 2, "中等": -6, "较差": -15}


def _level(score: int) -> str:
    return "可信" if score >= 80 else "一般" if score >= 65 else "谨慎" if score >= 45 else "高风险"


def analyze_seller(
    profile: SellerProfile,
    *,
    item_area: str = "",
    zhima: str = "",
    reg_days: int | None = None,
    sold_cnt: int | None = None,
    ip_hint: str = "",
    now: datetime | None = None,
) -> SellerAnalysis:
    a = SellerAnalysis(
        seller_id=profile.seller_id,
        nick=profile.nick,
        avatar=profile.avatar,
        introduction=profile.introduction,
        ip_location=profile.ip_location or ip_hint,
        item_area=item_area,
        zhima=zhima,
        reg_days=reg_days,
        sold_cnt=sold_cnt,
        seller_credit=profile.seller_credit,
        item_cnt=profile.item_cnt,
        rate_cnt=profile.rate_cnt,
    )
    a.ip_match, a.ip_note = compare_ip(a.ip_location, item_area)
    a.on_sale_sampled = sum(1 for i in profile.items if i.get("status") == "在售")
    a.sold_sampled = sum(1 for i in profile.items if i.get("status") == "已售")
    a.homogeneity = title_homogeneity([i.get("title") or "" for i in profile.items if i.get("status") == "在售"])
    a.dealer_words = [w for w in DEALER_WORDS if w in (profile.introduction or "")]
    a.ratings = d = rating_dynamics(profile.ratings, now)

    score = 70
    hi, risk = a.highlights, a.risks

    # 身份 / 资历
    for key, bonus in _ZHIMA_BONUS.items():
        if key in zhima:
            score += bonus
            if bonus >= 6:
                hi.append(f"芝麻信用「{zhima}」")
            elif bonus < 0:
                risk.append(f"芝麻信用仅「{zhima}」")
            break
    if reg_days is not None:
        if reg_days < 30:
            score -= 20
            risk.append(f"新注册账号（{reg_days} 天）")
        elif reg_days < 180:
            score -= 8
            risk.append(f"账号较新（{reg_days} 天）")
        elif reg_days >= 365 * 3:
            score += 5
            hi.append(f"老账号（{reg_days // 365} 年）")

    # IP 属地
    if a.ip_match == "match":
        score += 3
        hi.append(a.ip_note)
    elif a.ip_match == "mismatch":
        score -= 10
        risk.append(a.ip_note)
    elif a.ip_match == "overseas":
        score -= 15
        risk.append(a.ip_note)

    # 评价动态
    if d.as_seller == 0:
        score -= 5
        risk.append("暂无作为卖家的评价，交易记录不可考")
    else:
        rate = d.positive_rate or 0
        if d.as_seller >= 5 and rate < 0.9:
            score -= 15
            risk.append(f"卖家好评率仅 {rate:.0%}（样本 {d.as_seller} 条）")
        elif d.as_seller >= 5 and rate < 0.95:
            score -= 5
            risk.append(f"卖家好评率 {rate:.0%}，略低")
        elif d.as_seller >= 10 and rate >= 0.98:
            score += 6
            hi.append(f"卖家好评率 {rate:.0%}（样本 {d.as_seller} 条）")
        if d.trend == "down":
            score -= 10
            risk.append(
                f"近期口碑下滑：近 90 天好评率 {d.recent_positive_rate:.0%}，此前 {d.earlier_positive_rate:.0%}"
            )
        elif d.trend == "up" and d.recent_positive_rate and d.recent_positive_rate >= 0.95:
            hi.append("近期口碑向好")
        if d.recent_30d:
            hi.append(f"近 30 天有 {d.recent_30d} 条新评价，账号活跃")
        elif d.last_rated_at and (now or datetime.now(UTC)) - d.last_rated_at > timedelta(days=365):
            risk.append("最近一年没有新评价，可能是沉睡号 / 被转手的账号")
        if d.burst:
            score -= 8
            risk.append(f"{d.burst_note}，存在刷评或批量出货可能")
        if d.negative_hits:
            score -= min(20, 5 * len(d.negative_hits))
            risk.append("评价中出现：" + "、".join(f"{w}×{n}" for w, n in d.negative_hits[:5]))
        if d.positive_hits:
            hi.append("买家常提到：" + "、".join(w for w, _ in d.positive_hits[:4]))

    # 个人 / 贩子
    reasons: list[str] = []
    dealer_signals = 0
    if a.homogeneity >= 0.3:
        dealer_signals += 1
        reasons.append(f"在售商品标题高度同质（相似度 {a.homogeneity:.2f}）")
    if (profile.item_cnt or 0) >= 50:
        dealer_signals += 1
        reasons.append(f"累计商品 {profile.item_cnt} 件")
    if (sold_cnt or 0) >= 100:
        dealer_signals += 1
        reasons.append(f"已售出 {sold_cnt} 件")
    if a.dealer_words:
        dealer_signals += 1
        reasons.append("简介含商家话术：" + "、".join(a.dealer_words))
    if d.burst:
        dealer_signals += 1
    if dealer_signals >= 2:
        a.seller_type = "dealer"
    elif profile.items or d.as_seller:
        a.seller_type = "personal"
        reasons.append(
            "仅 1 项商家特征，暂按个人卖家看待" if dealer_signals else "在售商品品类分散、无商家话术，更像个人闲置"
        )
    a.type_reasons = reasons
    if a.seller_type == "dealer":
        risk.append("疑似贩子 / 商家：" + "；".join(reasons[:3]))

    a.score = max(0, min(100, score))
    a.level = _level(a.score)
    return a


# ---------------------------------------------------------------- 商品分析
class PricePoint(BaseModel):
    price: float
    seen_at: datetime


class ItemAnalysis(BaseModel):
    item_id: str
    title: str = ""
    price: float | None = None
    orig_price: float | None = None
    discount: float | None = None  # 现价 / 原价
    market: MarketStats | None = None
    sample_source: Literal["task", "keyword", "none"] = "none"
    percentile: int | None = None  # 在同类样本中的价格位置（0 = 最便宜）
    diff_to_median: float | None = None  # 相对中位数（-0.2 = 便宜 20%）
    deal_score: int | None = None
    deal_label: str = "样本不足"
    suspicious_low: bool = False
    want_cnt: int | None = None
    browse_cnt: int | None = None
    want_rate: float | None = None
    age_days: float | None = None
    want_per_day: float | None = None
    heat_level: Literal["高", "中", "低", "未知"] = "未知"
    price_points: list[PricePoint] = Field(default_factory=list)
    price_change: float | None = None  # 首次记录 → 当前
    desc_len: int = 0
    image_count: int = 0
    missing_info: list[str] = Field(default_factory=list)
    score: int = 0
    level: str = ""
    highlights: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


_KEY_INFO = {
    "成色": ("成色", "新", "划痕", "磕碰", "瑕疵"),
    "使用时长 / 购买时间": ("年", "月", "买的", "入手", "购于"),
    "维修 / 拆修史": ("拆", "修", "原装"),
    "配件 / 包装": ("配件", "原盒", "包装", "充电器", "盒"),
    "出售原因": ("出", "闲置", "换", "升级", "不用"),
}


def analyze_item(
    *,
    item_id: str,
    title: str,
    price: float | None,
    orig_price: float | None,
    want_cnt: int | None,
    browse_cnt: int | None,
    publish_time: datetime | None,
    desc: str,
    images: list[str],
    peers: list[float],
    sample_source: Literal["task", "keyword", "none"],
    snapshots: list[PricePoint],
    stats: MarketStats,
    now: datetime | None = None,
) -> ItemAnalysis:
    now = now or datetime.now(UTC)
    a = ItemAnalysis(
        item_id=item_id,
        title=title,
        price=price,
        orig_price=orig_price,
        want_cnt=want_cnt,
        browse_cnt=browse_cnt,
        desc_len=len(desc or ""),
        image_count=len(images),
        price_points=snapshots[-30:],
    )
    hi, risk = a.highlights, a.risks
    score = 60

    # 价格位置
    if stats.count:
        a.market, a.sample_source = stats, sample_source
    if price and orig_price and orig_price > price:
        a.discount = round(price / orig_price, 3)
    a.deal_score = deal_score(price, stats)
    a.deal_label = deal_label(a.deal_score)
    a.suspicious_low = suspicious_low(price, stats)
    if price and stats.count >= 5 and stats.median > 0:
        vals = sorted(p for p in peers if p and p > 0)
        a.percentile = int(round(100 * sum(1 for v in vals if v < price) / len(vals))) if vals else None
        a.diff_to_median = round(price / stats.median - 1, 3)
        if a.suspicious_low:
            score -= 20
            risk.append(f"价格不到同类 P25 的一半（P25 ¥{stats.p25:g}），警惕骗局、描述不符或监管机")
        elif a.diff_to_median <= -0.15:
            score += 15
            hi.append(f"比同类中位数便宜 {-a.diff_to_median:.0%}（中位数 ¥{stats.median:g}）")
        elif a.diff_to_median >= 0.15:
            score -= 10
            risk.append(f"比同类中位数贵 {a.diff_to_median:.0%}，议价空间较大")
    else:
        risk.append("同类价格样本不足，无法判断价格高低")

    # 价格走势
    if len(snapshots) >= 2 and snapshots[0].price:
        a.price_change = round(snapshots[-1].price / snapshots[0].price - 1, 3)
        if a.price_change <= -0.05:
            score += 5
            hi.append(f"已累计降价 {-a.price_change:.0%}，卖家出手意愿强")
        elif a.price_change >= 0.05:
            risk.append(f"价格上调了 {a.price_change:.0%}")

    # 热度
    if publish_time:
        pt = publish_time if publish_time.tzinfo else publish_time.replace(tzinfo=UTC)
        a.age_days = round(max((now - pt).total_seconds(), 0) / 86400, 1)
    if want_cnt is not None and browse_cnt:
        a.want_rate = round(want_cnt / browse_cnt, 3)
    if want_cnt is not None and a.age_days is not None:
        a.want_per_day = round(want_cnt / max(a.age_days, 0.5), 2)
    if a.want_per_day is not None:
        a.heat_level = "高" if a.want_per_day >= 5 else "中" if a.want_per_day >= 1 else "低"
        if a.heat_level == "高":
            hi.append(f"热度高：每天约 {a.want_per_day:g} 人想要，好价容易被抢，需尽快决定")
    if a.age_days is not None and a.age_days >= 60 and (want_cnt or 0) <= 3:
        risk.append(f"挂了 {a.age_days:.0f} 天仍少人问津，可能有隐藏问题或定价不合理")

    # 信息完整度
    if not images:
        score -= 10
        risk.append("没有实拍图")
    elif len(images) == 1:
        score -= 5
        risk.append("只有 1 张图，建议要求补充实拍")
    elif len(images) >= 4:
        score += 3
    text = f"{title} {desc or ''}"
    a.missing_info = [k for k, words in _KEY_INFO.items() if not any(w in text for w in words)]
    if a.desc_len < 15:
        score -= 8
        risk.append("描述过于简短")
    elif len(a.missing_info) <= 1 and a.desc_len >= 60:
        score += 5
        hi.append("描述信息完整")
    if any(w in text for w in ("微信", "vx", "VX", "加v", "QQ", "私聊加", "站外")):
        score -= 30
        risk.append("描述中出现站外联系方式，谨防引导私下交易")

    a.score = max(0, min(100, score))
    a.level = (
        "值得入手" if a.score >= 75 else "可以考虑" if a.score >= 60 else "谨慎考虑" if a.score >= 40 else "不建议"
    )
    return a


# ---------------------------------------------------------------- 大模型综合点评
class InsightOut(BaseModel):
    item_summary: str
    seller_summary: str
    ip_assessment: str
    comment_insight: str
    seller_type: Literal["personal", "dealer", "unknown"]
    trust_level: Literal["high", "medium", "low"]
    advice: str
    questions_for_seller: list[str]


INSIGHT_SYSTEM = """你是闲鱼二手交易顾问，根据系统给出的商品分析和商家分析数据，替买家写一份简明的购买参考。

要求：
1. item_summary：2~3 句，说明价格在市场中的位置、热度和信息是否充分。
2. seller_summary：2~3 句，结合信用、账号资历、在售商品判断是个人玩家还是贩子 / 商家。
3. ip_assessment：1~2 句，解读 IP 属地与发货地的关系（一致 / 不一致 / 境外 / 未知）及其风险，不要过度推断。
4. comment_insight：2~3 句，解读评价动态：近期口碑走向、是否集中评价、差评集中在什么问题。
5. trust_level：综合可信度；advice：一句话行动建议；questions_for_seller：2~4 条可直接发送的提问。
只依据提供的数据，不要编造；数据缺失就直说“数据不足”。"""


def _brief(d: dict[str, Any], drop: tuple[str, ...]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in drop and v not in (None, "", [], {})}


async def ai_insight(
    llm: LLMGateway, item: ItemAnalysis | None, seller: SellerAnalysis | None, criteria: str = ""
) -> InsightOut:
    parts = []
    if criteria:
        parts += ["# 买家需求", criteria[:1500]]
    if item:
        parts += ["# 商品分析", item.model_dump_json(exclude={"price_points"}, exclude_none=True)[:3000]]
    if seller:
        data = _brief(seller.model_dump(mode="json"), ("avatar", "fetched_at"))
        ratings = data.get("ratings") or {}
        ratings["recent"] = [
            f"{(r.get('created_at') or '')[:10]} [{r.get('rate')}] {r.get('content')}"
            for r in ratings.get("recent", [])
        ]
        ratings["negatives"] = [
            f"{(r.get('created_at') or '')[:10]} {r.get('content')}" for r in ratings.get("negatives", [])
        ]
        parts += ["# 商家分析", str(data)[:5000]]
    return await llm.complete_json(
        Tier.CHAT, INSIGHT_SYSTEM, "\n".join(parts), InsightOut, max_tokens=1500, effort="low"
    )
