import re
from zoneinfo import ZoneInfo
from db import connect
from psycopg.errors import UniqueViolation
IST = ZoneInfo("Asia/Kolkata")

def _fmt(ts):
    """Turn a database timestamp into '10:00 AM, Sun 18 Oct' in IST."""
    return ts.astimezone(IST).strftime("%I:%M %p, %a %d %b")

def list_slots(day: str) -> dict:
    """Free slots on one day. day = 'YYYY-MM-DD' (IST)."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, starts_at
            FROM slots
            WHERE NOT is_booked
              AND starts_at < now()
              AND (starts_at AT TIME ZONE 'Asia/Kolkata')::date = %s::date
            ORDER BY starts_at
            """,
            (day,),
        ).fetchall()
    return {
        "day": day,
        "slots": [{"slot_id": r["id"], "time": _fmt(r["starts_at"])} for r in rows],
    }


def book_slot(session_id: str, slot_id: int, name: str, phone: str) -> dict:
    key = f"{session_id}:{slot_id}"

    # phone must be a valid 10-digit Indian mobile number (starts with 6-9)
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        return {"ok": False, "error": "invalid_phone",
                "message": "Phone must be a valid 10-digit mobile number."}
    phone = digits

    try:
        with connect() as conn:
            with conn.transaction():          # BEGIN ... COMMIT (ROLLBACK on error)
                # 1. Lock the slot row. Other bookings for this slot wait here.
                slot = conn.execute(
                    "SELECT id, starts_at, is_booked FROM slots "
                    "WHERE id = %s FOR UPDATE",
                    (slot_id,),
                ).fetchone()
                if slot is None:
                    return {"ok": False, "error": "no_such_slot"}

                # 2. Did THIS chat already book THIS slot? (idempotency)
                existing = conn.execute(
                    "SELECT id, status FROM bookings WHERE idempotency_key = %s",
                    (key,),
                ).fetchone()
                if existing and existing["status"] == "confirmed":
                    return {"ok": True, "booking_id": existing["id"],
                            "time": _fmt(slot["starts_at"]), "duplicate": True}

                # 3. Someone else has it?
                if slot["is_booked"]:
                    return {"ok": False, "error": "taken"}

                # 4. One active booking per chat
                other = conn.execute(
                    "SELECT id FROM bookings WHERE split_part(idempotency_key, ':', 1) = %s "
                    "AND status = 'confirmed' AND slot_id <> %s",
                    (session_id, slot_id),
                ).fetchone()
                if other:
                    return {"ok": False, "error": "already_booked", "booking_id": other["id"],
                            "message": "This chat already has a booking. Cancel it first if the customer wants a different time."}

                # 5. Book it (reuse the row if this chat cancelled earlier)
                if existing:  # status was 'cancelled'
                    row = conn.execute(
                        "UPDATE bookings SET status = 'confirmed', "
                        "customer_name = %s, customer_phone = %s "
                        "WHERE id = %s RETURNING id",
                        (name, phone, existing["id"]),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "INSERT INTO bookings "
                        "(slot_id, customer_name, customer_phone, idempotency_key) "
                        "VALUES (%s, %s, %s, %s) RETURNING id",
                        (slot_id, name, phone, key),
                    ).fetchone()

                conn.execute(
                    "UPDATE slots SET is_booked = TRUE WHERE id = %s", (slot_id,)
                )
                return {"ok": True, "booking_id": row["id"],
                        "time": _fmt(slot["starts_at"]), "duplicate": False}
    except UniqueViolation:
        # Safety net fired: the partial index blocked a 2nd confirmed booking
        return {"ok": False, "error": "taken"}


def cancel_booking(session_id: str, booking_id: int) -> dict:
    with connect() as conn:
        with conn.transaction():
            b = conn.execute(
                "SELECT id, slot_id, status, idempotency_key FROM bookings "
                "WHERE id = %s FOR UPDATE",
                (booking_id,),
            ).fetchone()

            # Not found, or belongs to another chat -> same answer
            if b is None or b["idempotency_key"].rsplit(":", 1)[0] != session_id:
                return {"ok": False, "error": "not_found"}

            if b["status"] == "cancelled":
                return {"ok": True, "booking_id": b["id"], "already_cancelled": True}

            conn.execute(
                "UPDATE bookings SET status = 'cancelled' WHERE id = %s", (b["id"],)
            )
            conn.execute(
                "UPDATE slots SET is_booked = FALSE WHERE id = %s", (b["slot_id"],)
            )
            return {"ok": True, "booking_id": b["id"], "already_cancelled": False}


def handoff_to_human(session_id: str, reason: str) -> dict:
    with connect() as conn:
        # one handoff per chat: if staff were already notified, don't create another ticket
        existing = conn.execute(
            "SELECT id FROM handoffs WHERE session_id = %s ORDER BY id LIMIT 1",
            (session_id,),
        ).fetchone()
        if existing:
            return {"ok": True, "handoff_id": existing["id"], "already_handed_off": True,
                    "message": "Staff were already notified and will call back shortly."}
        row = conn.execute(
            "INSERT INTO handoffs (session_id, reason) VALUES (%s, %s) RETURNING id",
            (session_id, reason),
        ).fetchone()
    return {"ok": True, "handoff_id": row["id"],
            "message": "A staff member will call you back shortly."}
