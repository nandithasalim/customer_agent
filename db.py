import os
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()   # reads .env, so os.environ["DATABASE_URL"] works

# One pool for the whole app: connections are opened once and reused,
# instead of a new TLS handshake to the database for every query.
pool = ConnectionPool(
    os.environ["DATABASE_URL"],
    min_size=1,
    max_size=10,
    max_idle=240,                          # drop idle connections before Neon closes them
    check=ConnectionPool.check_connection, # test a connection before handing it out
    kwargs={"row_factory": dict_row, "prepare_threshold": None},  # no server-side prepared statements (safe with Neon's pooler)
    open=True,
)


def connect():
    # used as: with connect() as conn: ...
    # commits when the block ends (rolls back on error), then returns the connection to the pool
    return pool.connection()
