import re
from datetime import UTC, datetime
from typing import Any


def dig(obj: Any, *path: Any, default: Any = None) -> Any:
    """安全地按路径取值：dig(d, "data", "item", 0, "title")。"""
    cur = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int):
            cur = cur[key] if -len(cur) <= key < len(cur) else None
        else:
            return default
        if cur is None:
            return default
    return cur


_NUM = re.compile(r"(\d+(?:\.\d+)?)")


def parse_price(value: Any) -> float | None:
    """解析 '¥1,299'、'1.2万'、[{'text':'¥'},{'text':'99'}] 等多种价格表示。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        value = "".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in value)
    text = str(value).replace(",", "").replace("当前价", "").strip()
    m = _NUM.search(text)
    if not m:
        return None
    num = float(m.group(1))
    if "万" in text:
        num *= 10000
    return round(num, 2)


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    m = _NUM.search(str(value).replace(",", ""))
    if not m:
        return None
    num = float(m.group(1))
    if "万" in str(value):
        num *= 10000
    return int(num)


def parse_ms(value: Any) -> datetime | None:
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts / 1000 if ts > 10**11 else ts, tz=UTC)


def normalize_link(raw: str | None, item_id: str | None) -> str:
    if raw:
        if raw.startswith("fleamarket://"):
            raw = raw.replace("fleamarket://", "https://www.goofish.com/", 1)
        if raw.startswith("http"):
            return raw
    return f"https://www.goofish.com/item?id={item_id}" if item_id else ""
