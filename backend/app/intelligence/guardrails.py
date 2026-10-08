"""输出护栏与输入防御。

AI 生成的任何对外消息都必须经过 check_reply：
- 金额校验：回复中出现的任何价格都不得低于底价
- 站外引流：微信 / QQ / 支付宝 / 手机号 / 线下交易等
- 承诺性表述：保证正品、假一赔十 等
- 长度
"""

import re
from dataclasses import dataclass, field

OFF_PLATFORM_PATTERNS = [
    r"微信|威信|薇信|v信|vx|wx|weixin|wechat",
    r"qq|扣扣|企鹅号",
    r"支付宝|zfb|银行卡|转账|私下交易|线下交易|走鱼外|不走平台",
    r"加我|联系方式|电话联系",
    r"(?<!\d)1[3-9]\d{9}(?!\d)",
]
PROMISE_PATTERNS = [r"保证正品", r"假一(赔|罚)[十百]", r"绝对(没问题|正品)", r"包退包换", r"终身保修"]
INJECTION_PATTERNS = [
    r"忽略(之前|上面|以上)的?(所有)?(指令|提示|设定)",
    r"(系统|system)\s*(提示|prompt)",
    r"你(是|是不是)\s*(ai|机器人|人工智能|gpt|claude|chatgpt|自动回复)",
    r"(告诉|说出)我?(你的)?(底价|最低价|成本价)",
    r"prompt|jailbreak|developer\s*mode",
]

_OFF = [re.compile(p, re.IGNORECASE) for p in OFF_PLATFORM_PATTERNS]
_PROMISE = [re.compile(p) for p in PROMISE_PATTERNS]
_INJECT = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
_MONEY = re.compile(r"(?:¥|￥)?\s*(\d+(?:\.\d+)?)\s*(元|块|w|万|k|千)?", re.IGNORECASE)
_MONEY_CONTEXT = re.compile(r"(¥|￥|元|块|价|出|最低|给你|收你|少|便宜|包邮)")


def extract_amounts(text: str) -> list[float]:
    """提取文本中的价格数字（只取带价格语境的数字，避免把型号、容量误判为价格）。"""
    amounts: list[float] = []
    for m in _MONEY.finditer(text):
        value = float(m.group(1))
        unit = (m.group(2) or "").lower()
        window = text[max(0, m.start() - 4) : m.end() + 2]
        has_symbol = (
            text[max(0, m.start() - 1) : m.start() + 1].strip() in ("¥", "￥")
            or "¥" in m.group(0)
            or "￥" in m.group(0)
        )
        if not (unit or has_symbol or _MONEY_CONTEXT.search(window)):
            continue
        # 排除常见非价格：容量 / 型号 / 百分比 / 时间
        tail = text[m.end() : m.end() + 2].lower()
        if re.match(r"\s*(g|gb|t|tb|mah|寸|%|天|小时|分钟|年|个月|代|核|w\b)", tail) and not unit:
            continue
        if unit in ("w", "万"):
            value *= 10000
        elif unit in ("k", "千"):
            value *= 1000
        amounts.append(value)
    return amounts


@dataclass
class GuardResult:
    ok: bool
    violations: list[str] = field(default_factory=list)

    def add(self, v: str) -> None:
        self.ok = False
        self.violations.append(v)


def check_reply(
    text: str,
    *,
    floor_price: float | None = None,
    allowed_amounts: tuple[float, ...] = (),
    max_len: int = 200,
) -> GuardResult:
    r = GuardResult(ok=True)
    if not text.strip():
        r.add("empty")
        return r
    if len(text) > max_len:
        r.add("too_long")
    for p in _OFF:
        if p.search(text):
            r.add("off_platform")
            break
    for p in _PROMISE:
        if p.search(text):
            r.add("promise")
            break
    if floor_price is not None:
        allowed = set(allowed_amounts)
        for amount in extract_amounts(text):
            # 运费、赠品等小额数字不视为报价；明确允许的金额（如标价）放行
            if amount in allowed or amount < floor_price * 0.2:
                continue
            if amount < floor_price:
                r.add(f"below_floor:{amount:g}")
                break
    return r


def detect_injection(text: str) -> bool:
    return any(p.search(text) for p in _INJECT)


def sanitize_user_text(text: str, max_len: int = 500) -> str:
    """传给模型前的清洗：截断、去掉控制字符。"""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    return text[:max_len]
