from tixcraft_v17.parser.tixcraft import parse_price, parse_price_range, parse_status, parse_ticket_text

def test_section_not_price(): assert parse_price("紅217區 剩餘12") is None
def test_attached_price(): assert parse_price("3樓5800 剩餘12") == 5800
def test_range(): assert parse_price_range("平面特區 $5380-$8680") == (5380,8680)
def test_hot_sale(): assert parse_status("紅217區 熱賣中") == "熱賣中"
