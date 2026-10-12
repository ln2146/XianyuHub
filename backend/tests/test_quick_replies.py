from app.domains.goods.models import MyItem
from app.domains.message.router import generate_quick_replies
from app.domains.order.models import Order, OrderState


def test_unknown_product_never_promises_condition_shipping_or_automation():
    text = "\n".join(reply.text for reply in generate_quick_replies(None, [], 0))
    for unsupported in ("正品", "顺丰", "包邮", "当天", "今天", "自动发货", "现货", "多人咨询"):
        assert unsupported not in text


def test_product_replies_use_actual_description_and_price_without_inventing_terms():
    item = MyItem(title="二手耳机", status="on_sale", price=100, floor_price=80, desc="左耳有划痕，无发票")
    replies = generate_quick_replies(item, [], 0)
    text = "\n".join(reply.text for reply in replies)
    assert "左耳有划痕，无发票" in text and "100 元" in text and "90 元" in text
    for unsupported in ("功能完好", "成色很好", "顺丰", "今天", "成本价", "先拍先得", "自动发货"):
        assert unsupported not in text


def test_paid_order_acknowledges_payment_without_claiming_dispatch():
    paid = Order(status=OrderState.PAID)
    replies = generate_quick_replies(None, [paid], 0)
    assert any(reply.tag == "订单已付款" for reply in replies)
    assert "正在打包" not in "\n".join(reply.text for reply in replies)
    assert not any(reply.tag == "订单已付款" for reply in generate_quick_replies(None, [Order(status=OrderState.PENDING_PAY)], 0))


def test_sold_item_does_not_offer_to_sell_again():
    item = MyItem(title="耳机", status="sold", price=100, floor_price=80, desc="有划痕")
    assert not any(reply.tag in ("在售商品", "当前标价", "折中诚意") for reply in generate_quick_replies(item, [], 0))
