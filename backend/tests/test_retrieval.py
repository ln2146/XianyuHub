from app.intelligence.retrieval import select_knowledge, split_chunks, tokenize

KB = "\n".join(
    [
        "## 基本信息",
        "Switch 日版续航版，2022 年 6 月购入，一直贴膜带壳使用。",
        "",
        "## 配件",
        "原装底座、HDMI 线、电源适配器齐全，送两个 Joy-Con 硅胶套。",
        "",
        "## 电池",
        "电池续航正常，玩塞尔达大约 5 小时。",
        "",
        "## 瑕疵",
        "左摇杆有轻微漂移，已在售价中考虑。屏幕无划痕。",
        "",
        "## 发货",
        "顺丰到付，拍下后 24 小时内发货，同城可面交。",
    ]
    + [f"## 其他说明 {i}\n" + "这是一段与问题无关的补充说明文字，用于把知识库撑长。" * 4 for i in range(20)]
)


def test_tokenize_mixed():
    toks = tokenize("Switch 摇杆漂移吗")
    assert "switch" in toks and "摇杆" in toks and "漂移" in toks


def test_split_chunks_respects_headings_and_length():
    chunks = split_chunks(KB)
    assert any(c.startswith("## 瑕疵") for c in chunks)
    assert all(len(c) <= 300 for c in chunks)


def test_select_relevant_sections():
    out = select_knowledge(KB, "摇杆有没有漂移？", max_chars=300)
    assert "左摇杆有轻微漂移" in out and "顺丰" not in out
    out = select_knowledge(KB, "什么时候发货，能面交吗", max_chars=300)
    assert "24 小时内发货" in out
    # 短知识库原样返回；完全无关时退回开头的通用信息
    assert select_knowledge("短内容", "任意") == "短内容"
    assert "基本信息" in select_knowledge(KB, "zzzz", max_chars=200)
