import os
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()   # reads .env, so os.environ["DATABASE_URL"] works

def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)