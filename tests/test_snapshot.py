"""Unit tests for the MIS intraday snapshot parsing helpers."""
from data.fetcher_snapshot import _current_price, _num, _ex_ch


def test_num_handles_dash_and_blank():
    assert _num("2400.0") == 2400.0
    assert _num("-") is None
    assert _num("") is None
    assert _num(None) is None


def test_ex_ch_prefix():
    assert _ex_ch("2330", "TWSE") == "tse_2330.tw"
    assert _ex_ch("6488", "TPEX") == "otc_6488.tw"


def test_current_price_prefers_last_deal():
    item = {"z": "2400.0", "a": "2405.0_", "b": "2395.0_", "o": "2440.0", "y": "2410.0"}
    assert _current_price(item) == 2400.0


def test_current_price_falls_back_to_bid_ask_midpoint():
    # z is '-' (no deal this tick) → midpoint of best ask/bid.
    item = {"z": "-", "a": "2405.0_2410.0_", "b": "2395.0_2390.0_", "o": "2440.0", "y": "2410.0"}
    assert _current_price(item) == 2400.0


def test_current_price_falls_back_to_open_then_prev():
    assert _current_price({"z": "-", "a": "-", "b": "-", "o": "2440.0", "y": "2410.0"}) == 2440.0
    assert _current_price({"z": "-", "a": "", "b": "", "o": "-", "y": "2410.0"}) == 2410.0
