"""mtop 签名与各类 ID 生成。"""

import hashlib
import random
import string
import time
import uuid

MTOP_APP_KEY = "34839810"
IM_APP_KEY = "444e9908a51d1cb236a27862abc769c9"


def now_ms() -> int:
    return int(time.time() * 1000)


def mtop_sign(token: str, t: int | str, data: str, app_key: str = MTOP_APP_KEY) -> str:
    """sign = md5(token & t & appKey & data)，data 为请求体 JSON 原文。"""
    raw = f"{token}&{t}&{app_key}&{data}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def gen_cna() -> str:
    """匿名访客标识（24~25 位字母数字）。"""
    return "".join(random.choices(string.ascii_letters + string.digits, k=24))


def gen_mid() -> str:
    """LWP 消息 ID：3 位随机数 + 毫秒时间戳 + ' 0'。"""
    return f"{random.randint(0, 999)}{now_ms()} 0"


def gen_uuid() -> str:
    """消息体 uuid。"""
    return f"-{now_ms()}{random.randint(1, 9)}"


def gen_device_id(user_id: str) -> str:
    """IM 设备 ID：UUID 风格随机串 + '-' + unb。同一账号应持久化复用。"""
    return f"{str(uuid.uuid4()).upper()}-{user_id}"
