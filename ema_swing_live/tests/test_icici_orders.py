from ema_swing_live import icici


def test_gtt_payload_resolves_etf_alias_without_network():
    payload = icici.build_gtt_single_leg_payload(
        symbol="NSE:GOLDBEES",
        side="BUY",
        quantity="2",
        trigger_price="70.123",
        limit_price="70.5",
    )

    assert payload["exchange_code"] == "NSE"
    assert payload["stock_code"] == "GOLDEX"
    assert payload["product"] == "cash"
    assert payload["quantity"] == "2"
    assert payload["gtt_type"] == "single"
    assert payload["right"] == "others"
    assert payload["strike_price"] == "0"
    assert payload["order_details"] == [
        {
            "action": "buy",
            "order_type": "limit",
            "limit_price": "70.50",
            "trigger_price": "70.12",
        }
    ]


def test_gtt_dry_run_does_not_require_credentials():
    result = icici.place_gtt_single_leg_order(
        symbol="GOLDEX",
        side="SELL",
        quantity=1,
        trigger_price=75,
        limit_price=74.5,
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["payload"]["stock_code"] == "GOLDEX"
    assert result["response"] is None


def test_limit_payload_resolves_etf_alias_without_network():
    payload = icici.build_limit_order_payload(
        symbol="NSE:GOLDBEES",
        side="BUY",
        quantity="2",
        limit_price="70.5",
    )

    assert payload["exchange_code"] == "NSE"
    assert payload["stock_code"] == "GOLDEX"
    assert payload["product"] == "cash"
    assert payload["action"] == "buy"
    assert payload["order_type"] == "limit"
    assert payload["quantity"] == "2"
    assert payload["price"] == "70.50"
    assert payload["validity"] == "day"
    assert payload["right"] == "others"
    assert payload["strike_price"] == "0"


def test_limit_dry_run_does_not_require_credentials():
    result = icici.place_limit_order(
        symbol="GOLDEX",
        side="SELL",
        quantity=1,
        limit_price=74.5,
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["payload"]["stock_code"] == "GOLDEX"
    assert result["response"] is None


def test_limit_user_remark_is_alphanumeric_only():
    payload = icici.build_limit_order_payload(
        symbol="GOLDEX",
        side="BUY",
        quantity=1,
        limit_price=70,
        user_remark="ema_swing-1!",
    )

    assert payload["user_remark"] == "emaswing1"


def test_limit_payload_supports_mtf_product():
    payload = icici.build_limit_order_payload(
        symbol="GOLDEX",
        side="BUY",
        quantity=1,
        limit_price=70,
        product="mtf",
    )

    assert payload["product"] == "mtf"


def test_icici_portfolio_position_maps_alias_and_derives_mtf_loan():
    row = icici._normalized_broker_position(
        {
            "stock_code": "HANBEE",
            "quantity": "185",
            "average_price": "539.88",
            "margin_amount": "24320.24",
            "buy_date": "2026-05-09T09:15:00",
        }
    )

    assert row["date"] == "2026-05-09"
    assert row["symbol"] == "NSE:HNGSNGBEES"
    assert row["funding_mode"] == "mtf"
    assert round(row["value"], 2) == 99877.80
    assert round(row["mtf_loan"], 2) == 75557.56
