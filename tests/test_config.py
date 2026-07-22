"""Unit tests for config.clean_number — TWSE/TPEX numeric string parsing."""
from config import clean_number


def test_clean_number_plain():
    assert clean_number("123") == 123.0
    assert clean_number(123) == 123.0
    assert clean_number(123.5) == 123.5


def test_clean_number_none_is_zero():
    assert clean_number(None) == 0.0


def test_clean_number_commas_and_plus():
    assert clean_number("1,234") == 1234.0
    assert clean_number("+56") == 56.0
    assert clean_number("+1,234") == 1234.0


def test_clean_number_negative():
    assert clean_number("-1,234") == -1234.0


def test_clean_number_double_dash_is_zero():
    """TWSE uses '--' as a literal 'no data' placeholder."""
    assert clean_number("--") == 0.0


def test_clean_number_tpex_up_down_markers():
    """TPEX uses △ (up) and ▽ (down) instead of a leading sign."""
    assert clean_number("△12") == 12.0
    assert clean_number("▽12") == -12.0


def test_clean_number_garbage_is_zero():
    assert clean_number("N/A") == 0.0
    assert clean_number("") == 0.0
