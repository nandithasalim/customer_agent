# race_test.py
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from tools import list_slots, book_slot
from db import connect

day = (date.today() + timedelta(days=2)).isoformat()   # fresh day, untouched slots
free = list_slots(day)["slots"]
slot_a = free[0]["slot_id"]
slot_b = free[1]["slot_id"]

def confirmed_rows(slot_id):
    with connect() as conn:
        return conn.execute(
            "SELECT count(*) AS n FROM bookings WHERE slot_id = %s AND status = 'confirmed'",
            (slot_id,),
        ).fetchone()["n"]

# ---------- Test 1: 20 different customers, same slot ----------
N = 20
start = threading.Barrier(N)

def customer(i):
    start.wait()                                   # everyone starts together
    return book_slot(f"race-{i}", slot_a, f"Customer {i}", f"90000000{i:02d}")

with ThreadPoolExecutor(max_workers=N) as pool:
    results = list(pool.map(customer, range(N)))

wins  = [r for r in results if r["ok"]]
taken = [r for r in results if not r["ok"] and r["error"] == "taken"]
print(f"Test 1: {len(wins)} won, {len(taken)} taken, DB rows = {confirmed_rows(slot_a)}")
assert len(wins) == 1 and len(taken) == N - 1 and confirmed_rows(slot_a) == 1

# ---------- Test 2: same chat, 10 identical requests ----------
M = 10
start2 = threading.Barrier(M)

def retry(_):
    start2.wait()
    return book_slot("retry-chat", slot_b, "Anu", "9999900000")

with ThreadPoolExecutor(max_workers=M) as pool:
    results2 = list(pool.map(retry, range(M)))

ids = {r["booking_id"] for r in results2 if r["ok"]}
print(f"Test 2: {sum(r['ok'] for r in results2)}/{M} ok, distinct booking ids = {ids}, "
      f"DB rows = {confirmed_rows(slot_b)}")
assert len(ids) == 1 and confirmed_rows(slot_b) == 1

print("PASS: no double bookings under concurrency")