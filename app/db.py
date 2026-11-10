"""PostgreSQL в проде (DATABASE_URL), SQLite на компьютере."""
import os
import sqlite3
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SQLITE_PATH = os.environ.get("SQLITE_PATH", "ascend.db")
IS_PG = DATABASE_URL.startswith("postgres")
SERIAL = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id BIGINT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', aura BIGINT NOT NULL DEFAULT 0,
        vip INTEGER NOT NULL DEFAULT 0, ver BIGINT NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT '{}',
        rating INTEGER NOT NULL DEFAULT 0, referrer BIGINT, ref_paid INTEGER NOT NULL DEFAULT 0,
        friends INTEGER NOT NULL DEFAULT 0, ad_day BIGINT NOT NULL DEFAULT 0, ad_today INTEGER NOT NULL DEFAULT 0,
        ad_credits INTEGER NOT NULL DEFAULT 0, created BIGINT NOT NULL DEFAULT 0, seen BIGINT NOT NULL DEFAULT 0)""",
    f"""CREATE TABLE IF NOT EXISTS gifts (
        id {SERIAL}, kind TEXT NOT NULL, num INTEGER NOT NULL, owner BIGINT NOT NULL,
        model TEXT NOT NULL DEFAULT '', backdrop TEXT NOT NULL DEFAULT '', pattern TEXT NOT NULL DEFAULT '',
        price BIGINT, shown INTEGER NOT NULL DEFAULT 1, created BIGINT NOT NULL DEFAULT 0)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS gifts_num ON gifts (kind, num)",
    "CREATE INDEX IF NOT EXISTS gifts_owner ON gifts (owner)",
    "CREATE INDEX IF NOT EXISTS users_rating ON users (rating DESC)",
    """CREATE TABLE IF NOT EXISTS payments (
        charge_id TEXT PRIMARY KEY, user_id BIGINT NOT NULL, pack TEXT NOT NULL, stars INTEGER NOT NULL,
        refunded INTEGER NOT NULL DEFAULT 0, created BIGINT NOT NULL)""",
]


class Tx:
    def __init__(self, conn):
        self.conn = conn

    def run(self, sql, params=()):
        if IS_PG:
            sql = sql.replace("?", "%s")
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur

    def one(self, sql, params=()):
        row = self.run(sql, params).fetchone()
        return dict(row) if row is not None else None

    def all(self, sql, params=()):
        return [dict(r) for r in self.run(sql, params).fetchall()]


def _connect():
    if IS_PG:
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    conn = sqlite3.connect(SQLITE_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def tx():
    conn = _connect()
    try:
        yield Tx(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    with tx() as t:
        for statement in SCHEMA:
            t.run(statement)
