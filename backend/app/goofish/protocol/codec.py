"""IM 推送数据解码：base64 → JSON（非聊天包）或 MessagePack（聊天 / 系统消息）。"""

import base64
import binascii
import json
from typing import Any

import msgpack


def _normalize(obj: Any) -> Any:
    """统一为 JSON 友好的结构：dict 的 key 全部转为 str，bytes 尝试解码为 utf-8。"""
    if isinstance(obj, dict):
        return {str(_normalize(k)): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(obj).decode("ascii")
    if isinstance(obj, msgpack.ExtType):
        return {"__ext__": obj.code, "data": base64.b64encode(obj.data).decode("ascii")}
    return obj


def decode_push_data(data: str) -> tuple[str, Any]:
    """返回 (kind, obj)。kind: json / msgpack / invalid。"""
    try:
        raw = base64.b64decode(data, validate=False)
    except (binascii.Error, ValueError):
        return "invalid", None
    try:
        return "json", json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    try:
        unpacker = msgpack.Unpacker(raw=True, strict_map_key=False)
        unpacker.feed(raw)
        obj = next(unpacker)
        return "msgpack", _normalize(obj)
    except Exception:  # noqa: BLE001 - 任意损坏数据都视为无效
        return "invalid", None


def encode_custom(payload: dict[str, Any]) -> str:
    """发送消息时 custom.data 的编码：base64(JSON)。"""
    return base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
