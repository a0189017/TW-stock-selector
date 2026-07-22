"""Unit tests for TWSE 三大法人 (T86) parsing and consecutive-streak computation."""
import pandas as pd

from data.fetcher_chip import _parse_t86, _compute_consec_streaks


# ---------------------------------------------------------------------------
# _parse_t86
# ---------------------------------------------------------------------------

def test_parse_t86_basic():
    data = {
        "stat": "OK",
        "fields": ["證券代號", "證券名稱", "外資及陸資買賣超股數(不含外資自營商)",
                  "投信買賣超股數", "自營商買賣超股數", "三大法人買賣超股數"],
        "data": [["2330", "台積電", "1000000", "200000", "50000", "1250000"]],
    }
    df = _parse_t86(data)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["code"] == "2330"
    assert row["foreign_net"] == 1000.0    # shares -> 張 (/1000)
    assert row["trust_net"] == 200.0
    assert row["big3_net"] == 1250.0


def test_parse_t86_bad_stat_or_missing_fields():
    assert _parse_t86({"stat": "ERROR"}).empty
    assert _parse_t86({}).empty
    assert _parse_t86({"stat": "OK", "fields": [], "data": []}).empty


def test_parse_t86_missing_required_column():
    """If a required column (e.g. 投信) can't be found, return empty rather than guessing."""
    data = {
        "stat": "OK",
        "fields": ["證券代號", "證券名稱"],   # no 外資/投信/三大法人 columns at all
        "data": [["2330", "台積電"]],
    }
    assert _parse_t86(data).empty


def test_parse_t86_skips_invalid_code():
    data = {
        "stat": "OK",
        "fields": ["證券代號", "外資及陸資買賣超股數", "投信買賣超股數", "三大法人買賣超股數"],
        "data": [
            ["ABCD", "1000", "1000", "1000"],   # non-numeric code
            ["2330", "1000", "1000", "1000"],
        ],
    }
    df = _parse_t86(data)
    assert list(df["code"]) == ["2330"]


# ---------------------------------------------------------------------------
# _compute_consec_streaks
# ---------------------------------------------------------------------------

def _combined(rows):
    """rows: list of (code, date, foreign_net) most-recent-date-last is fine —
    the function sorts internally."""
    return pd.DataFrame(rows, columns=["code", "date", "foreign_net"])


def test_consec_streak_all_buy():
    df = _combined([
        ("2330", "20260101", 100),
        ("2330", "20260102", 200),
        ("2330", "20260103", 300),
    ])
    buy, sell = _compute_consec_streaks(df)
    assert buy["2330"] == 3
    assert sell["2330"] == 0


def test_consec_streak_all_sell():
    df = _combined([
        ("2330", "20260101", -100),
        ("2330", "20260102", -200),
    ])
    buy, sell = _compute_consec_streaks(df)
    assert buy["2330"] == 0
    assert sell["2330"] == 2


def test_consec_streak_stops_at_flip():
    """Buy, buy, then a sell on the most recent day → only today's sell counts."""
    df = _combined([
        ("2330", "20260101", 100),
        ("2330", "20260102", 100),
        ("2330", "20260103", -50),
    ])
    buy, sell = _compute_consec_streaks(df)
    assert sell["2330"] == 1
    assert buy["2330"] == 0


def test_consec_streak_stops_at_zero_net():
    df = _combined([
        ("2330", "20260101", 100),
        ("2330", "20260102", 0),
        ("2330", "20260103", 100),
    ])
    buy, sell = _compute_consec_streaks(df)
    # Most recent day (0103) is a buy, but the day before is net==0 -> streak stops there.
    assert buy["2330"] == 1


def test_consec_streak_multiple_codes_independent():
    df = _combined([
        ("2330", "20260101", 100),
        ("6488", "20260101", -100),
        ("2330", "20260102", 100),
        ("6488", "20260102", -100),
    ])
    buy, sell = _compute_consec_streaks(df)
    assert buy["2330"] == 2 and sell["2330"] == 0
    assert buy["6488"] == 0 and sell["6488"] == 2
