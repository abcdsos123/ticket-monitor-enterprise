from tixcraft_v17.parser.tixcraft import parse_ticket_text


def test_parse_english_remaining():
    result = parse_ticket_text("VIP A NT$6,880 熱賣中 15 seat(s) remaining")
    assert result["area"] == "VIP A"
    assert result["price"] == 6880
    assert result["remaining"] == 15
    assert result["status"] == "有票"


def test_parse_chinese_remaining():
    result = parse_ticket_text("黃2A NT$3,880 剩餘 8 張")
    assert result["remaining"] == 8
    assert result["status"] == "有票"


def test_available_without_number_is_unknown_quantity():
    result = parse_ticket_text("VIP B NT$5,880 熱賣中")
    assert result["remaining"] is None
    assert result["status"] == "有票"


def test_attached_price_and_remaining_are_parsed_stably():
    row = parse_ticket_text("3樓5800 剩餘 12")
    assert row["area"] == "3樓"
    assert row["price"] == 5800
    assert row["remaining"] == 12
    assert row["status"] == "有票"


def test_remaining_wins_over_leaked_sold_word():
    row = parse_ticket_text("4樓4800 剩餘 58 已售完")
    assert row["price"] == 4800
    assert row["remaining"] == 58
    assert row["status"] == "有票"
