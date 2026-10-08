"""商品发布请求体构造（mtop.idle.pc.idleitem.publish）。"""

import random
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.goofish.parsers.common import dig


class ShippingMode(StrEnum):
    FREE = "free"  # 包邮
    BY_DISTANCE = "by_distance"  # 按距离计费
    FIXED = "fixed"  # 一口价运费
    NO_SHIPPING = "no_shipping"  # 无需邮寄（虚拟商品）


class UploadedImage(BaseModel):
    url: str
    width: int
    height: int


class PublishDraft(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    desc: str = Field(min_length=1, max_length=5000)
    images: list[UploadedImage] = Field(min_length=1, max_length=9)
    price: float = Field(gt=0)
    orig_price: float | None = None
    quantity: int = Field(default=1, ge=1)
    shipping: ShippingMode = ShippingMode.FREE
    post_fee: float = 0
    self_pickup: bool = False


def _image_info(img: UploadedImage, major: bool) -> dict[str, Any]:
    return {
        "extraInfo": {"isH": "false", "isT": "false", "raw": "false"},
        "isQrCode": False,
        "url": img.url,
        "heightSize": img.height,
        "widthSize": img.width,
        "major": major,
        "type": 0,
        "status": "done",
    }


def unique_code() -> str:
    return str(random.randint(10**15, 10**16 - 1))


def build_category_request(title: str, desc: str, images: list[UploadedImage]) -> dict[str, Any]:
    return {
        "title": title,
        "lockCpv": False,
        "multiSKU": False,
        "publishScene": "mainPublish",
        "scene": "newPublishChoice",
        "description": desc,
        "imageInfos": [_image_info(img, i == 0) for i, img in enumerate(images)],
        "uniqueCode": unique_code(),
    }


def build_publish_payload(draft: PublishDraft, category: dict[str, Any], address: dict[str, Any]) -> dict[str, Any]:
    """category 为类目推荐接口返回的 data，address 为默认地址接口返回的一条 commonAddresses。"""
    post: dict[str, Any] = {"canFreeShipping": False, "supportFreight": False, "onlyTakeSelf": False}
    if draft.shipping == ShippingMode.FREE:
        post.update(canFreeShipping=True, supportFreight=True)
    elif draft.shipping == ShippingMode.BY_DISTANCE:
        post.update(supportFreight=True, templateId="-100")
    elif draft.shipping == ShippingMode.FIXED:
        post.update(supportFreight=True, templateId="0", postPriceInCent=str(int(round(draft.post_fee * 100))))
    else:
        post.update(templateId="0")

    price: dict[str, Any] = {"priceInCent": str(int(round(draft.price * 100)))}
    if draft.orig_price:
        price["origPriceInCent"] = str(int(round(draft.orig_price * 100)))

    labels = []
    for card in dig(category, "cardList", default=[]) or []:
        cd = card.get("cardData") or {}
        for v in cd.get("valuesList") or []:
            if v.get("isClicked"):
                labels.append(
                    {
                        "channelCateName": v.get("catName"),
                        "channelCateId": v.get("channelCatId"),
                        "tbCatId": v.get("tbCatId"),
                        "labelType": "common",
                        "propertyName": cd.get("propertyName"),
                        "isUserClick": "1",
                        "from": "newPublishChoice",
                        "propertyId": cd.get("propertyId"),
                        "labelFrom": "newPublish",
                        "text": v.get("catName"),
                        "properties": f"{cd.get('propertyId')}##{cd.get('propertyName')}:"
                        f"{v.get('channelCatId')}##{v.get('catName')}",
                    }
                )
                break
    cat = category.get("categoryPredictResult") or {}
    payload: dict[str, Any] = {
        "freebies": False,
        "itemTypeStr": "b",
        "quantity": str(draft.quantity),
        "simpleItem": "true",
        "imageInfoDOList": [_image_info(img, True) for img in draft.images],
        "itemTextDTO": {"desc": draft.desc, "title": draft.title, "titleDescSeparate": True},
        "itemLabelExtList": labels,
        "itemPriceDTO": price,
        "userRightsProtocols": [{"enable": False, "serviceCode": "SKILL_PLAY_NO_MIND"}],
        "itemPostFeeDTO": post,
        "itemAddrDTO": {
            "area": address.get("area"),
            "city": address.get("city"),
            "divisionId": address.get("divisionId"),
            "gps": f"{address.get('longitude')},{address.get('latitude')}",
            "poiId": address.get("poiId"),
            "poiName": address.get("poi"),
            "prov": address.get("prov"),
        },
        "defaultPrice": False,
        "itemCatDTO": {
            "catId": str(cat.get("catId", "")),
            "catName": str(cat.get("catName", "")),
            "channelCatId": str(cat.get("channelCatId", "")),
            "tbCatId": str(cat.get("tbCatId", "")),
        },
        "uniqueCode": unique_code(),
        "sourceId": "pcMainPublish",
        "bizcode": "pcMainPublish",
        "publishScene": "pcMainPublish",
    }
    if draft.self_pickup:
        payload["onlyTakeSelf"] = True
    return payload
