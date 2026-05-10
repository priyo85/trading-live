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
