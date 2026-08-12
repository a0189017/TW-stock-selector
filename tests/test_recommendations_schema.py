"""Tests for the `screened` table schema migration (data/recommendations.py).

Verifies an existing (pre-multi-factor) database gains the new columns
without erroring or losing data — CREATE TABLE IF NOT EXISTS alone can't do
this since it no-ops against a table that already exists with fewer columns.
"""
import sqlite3

import pytest

import data.recommendations as rec


@pytest.fixture
def old_schema_db(tmp_path, monkeypatch):
    """A recommendations.db using the schema from before multi-factor columns existed."""
    db_path = tmp_path / "recommendations.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE screened (
            date TEXT NOT NULL, code TEXT NOT NULL, name TEXT, exchange TEXT,
            close REAL, tech_score INTEGER, rs20 REAL, rev_yoy REAL, rank INTEGER,
            PRIMARY KEY (date, code)
        )
    """)
    conn.execute("INSERT INTO screened VALUES ('2026-01-01','2330','TSMC','TWSE',1000,60,10,5,1)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(rec, "_DB_PATH", db_path)
    return db_path


def test_migration_adds_new_columns_without_error(old_schema_db):
    conn = rec._conn()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(screened)").fetchall()}
    conn.close()
    for col in ("chip_score", "fundamental_score", "sector_score", "rs60", "total_score", "strategy"):
        assert col in cols


def test_migration_preserves_existing_row(old_schema_db):
    conn = rec._conn()
    row = conn.execute("SELECT code, tech_score, chip_score FROM screened WHERE code='2330'").fetchone()
    conn.close()
    assert row == ("2330", 60, None)


def test_migration_is_idempotent(old_schema_db):
    """Calling _conn() (and therefore _migrate_schema) twice must not error."""
    rec._conn().close()
    rec._conn().close()


def test_save_screening_writes_new_columns(old_schema_db):
    n = rec.save_screening([{
        "code": "2317", "name": "Foxconn", "exchange": "TWSE", "close": 250,
        "tech_score": 70, "rs20": 8, "rev_yoy": 20,
        "chip_score": 15, "fundamental_score": 10, "sector_score": 4,
        "rs60": 12, "total_score": 99, "strategy": "trend",
    }], date="2026-01-02")
    assert n == 1

    conn = rec._conn()
    row = conn.execute(
        "SELECT chip_score, fundamental_score, sector_score, rs60, total_score, strategy "
        "FROM screened WHERE code='2317'"
    ).fetchone()
    conn.close()
    assert row == (15.0, 10.0, 4.0, 12.0, 99.0, "trend")


def test_save_screening_without_new_fields_stores_null(old_schema_db):
    """fetch_backtest_picks candidates never carry multi-factor fields — must
    not error, should just store NULL (evaluate_performance already tolerates it)."""
    n = rec.save_screening([{
        "code": "2317", "name": "Foxconn", "exchange": "TWSE", "close": 250,
        "tech_score": 70, "rs20": 8, "rev_yoy": 20,
    }], date="2026-01-03")
    assert n == 1

    conn = rec._conn()
    row = conn.execute(
        "SELECT chip_score, total_score, strategy FROM screened WHERE date='2026-01-03'"
    ).fetchone()
    conn.close()
    assert row == (None, None, None)
