"""Unit tests for TWSE/TPEX universe parsers (pure, no network)."""
import csv
import io

from data.fetcher_universe import (
    _parse_twse_openapi, _parse_twse_rwd_csv, _parse_twse_rwd, _rwd_csv_date,
    _parse_tpex, _parse_tpex_rwd, _roc_date_to_gregorian,
)


# ---------------------------------------------------------------------------
# _roc_date_to_gregorian
# ---------------------------------------------------------------------------

def test_roc_date_to_gregorian():
    assert _roc_date_to_gregorian("1150513") == "20260513"


def test_roc_date_to_gregorian_invalid_length():
    assert _roc_date_to_gregorian("20260513") == ""   # already 8 digits, not ROC 7
    assert _roc_date_to_gregorian("115051") == ""      # too short


def test_roc_date_to_gregorian_garbage():
    assert _roc_date_to_gregorian("abcdefg") == ""
    assert _roc_date_to_gregorian(None) == ""


# ---------------------------------------------------------------------------
# _parse_twse_openapi
# ---------------------------------------------------------------------------

def test_parse_twse_openapi_basic():
    data = [{
        "Code": "2330", "Name": "台積電", "ClosingPrice": "1000",
        "Change": "10", "TradeValue": "50000000", "OpeningPrice": "990",
        "HighestPrice": "1005", "LowestPrice": "985", "TradeVolume": "50000",
        "Transaction": "100",
    }]
    rows = _parse_twse_openapi(data)
    assert len(rows) == 1
    r = rows[0]
    assert r["code"] == "2330" and r["exchange"] == "TWSE"
    assert r["close"] == 1000.0 and r["change"] == 10.0
    assert r["change_pct"] == round(10 / 990 * 100, 2)


def test_parse_twse_openapi_skips_invalid_code_and_zero_price():
    data = [
        {"Code": "0050", "ClosingPrice": "100", "TradeValue": "1000"},   # ETF-looking code still 4-digit, kept by parser (exclude_etfs handles ETF filtering elsewhere)
        {"Code": "ABCD", "ClosingPrice": "100", "TradeValue": "1000"},   # non-digit code
        {"Code": "1234", "ClosingPrice": "0", "TradeValue": "1000"},     # zero close
        {"Code": "1235", "ClosingPrice": "100", "TradeValue": "0"},      # zero trade value
    ]
    rows = _parse_twse_openapi(data)
    codes = {r["code"] for r in rows}
    assert codes == {"0050"}


def test_parse_twse_openapi_empty():
    assert _parse_twse_openapi([]) == []
    assert _parse_twse_openapi(None) == []


# ---------------------------------------------------------------------------
# TWSE RWD (CSV form, and legacy JSON form)
# ---------------------------------------------------------------------------

def _rwd_csv_text(rows, fields=None):
    fields = fields or ["日期", "證券代號", "證券名稱", "成交股數", "成交金額",
                        "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(fields)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def test_parse_twse_rwd_csv_basic():
    text = _rwd_csv_text([
        ["1150721", "2330", "台積電", "50000", "50000000", "990", "1005", "985", "1000", "10", "100"],
    ])
    rows = _parse_twse_rwd_csv(text)
    assert len(rows) == 1
    r = rows[0]
    assert r["code"] == "2330" and r["name"] == "台積電"
    assert r["close"] == 1000.0 and r["change"] == 10.0
    assert r["exchange"] == "TWSE"


def test_parse_twse_rwd_csv_date_extraction():
    text = _rwd_csv_text([
        ["1150721", "2330", "台積電", "50000", "50000000", "990", "1005", "985", "1000", "10", "100"],
    ])
    assert _rwd_csv_date(text) == "20260721"


def test_parse_twse_rwd_csv_empty_or_no_header():
    assert _parse_twse_rwd_csv("") == []
    assert _parse_twse_rwd_csv("some,unrelated,header\n1,2,3\n") == []
    assert _rwd_csv_date("") == ""


def test_parse_twse_rwd_legacy_json():
    """Legacy JSON shape (stat/fields/data) — kept for backward compatibility."""
    data = {
        "stat": "OK",
        "fields": ["證券代號", "證券名稱", "開盤價", "最高價", "最低價", "收盤價",
                  "漲跌價差", "成交股數", "成交金額", "成交筆數"],
        "data": [["2330", "台積電", "990", "1005", "985", "1000", "10", "50000", "50000000", "100"]],
    }
    rows = _parse_twse_rwd(data)
    assert len(rows) == 1
    assert rows[0]["code"] == "2330"
    assert rows[0]["close"] == 1000.0


def test_parse_twse_rwd_legacy_json_bad_stat():
    assert _parse_twse_rwd({"stat": "ERROR"}) == []
    assert _parse_twse_rwd({}) == []


# ---------------------------------------------------------------------------
# TPEX
# ---------------------------------------------------------------------------

def test_parse_tpex_basic():
    data = [{
        "SecuritiesCompanyCode": "6488", "CompanyName": "環球晶",
        "Close": "1200", "Change": "50", "TransactionAmount": "10000000",
        "Open": "1150", "High": "1210", "Low": "1140",
        "TradingShares": "10000", "TransactionNumber": "50",
    }]
    rows = _parse_tpex(data)
    assert len(rows) == 1
    r = rows[0]
    assert r["code"] == "6488" and r["exchange"] == "TPEX"
    assert r["close"] == 1200.0 and r["change"] == 50.0


def test_parse_tpex_empty():
    assert _parse_tpex([]) == []
    assert _parse_tpex(None) == []


def test_parse_tpex_rwd_basic():
    data = {
        "iTotalRecords": 1,
        "aaData": [["6488", "環球晶", "1200", "50"]],
    }
    rows = _parse_tpex_rwd(data)
    assert len(rows) == 1
    assert rows[0]["code"] == "6488"
    assert rows[0]["close"] == 1200.0


def test_parse_tpex_rwd_no_records():
    assert _parse_tpex_rwd({"iTotalRecords": 0, "aaData": []}) == []
    assert _parse_tpex_rwd({}) == []
