CREATE TABLE IF NOT EXISTS slots (
  id         SERIAL PRIMARY KEY,
  starts_at  TIMESTAMPTZ NOT NULL UNIQUE,
  is_booked  BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS bookings (
  id               SERIAL PRIMARY KEY,
  slot_id          INT NOT NULL REFERENCES slots(id),
  customer_name    TEXT NOT NULL,
  customer_phone   TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'confirmed',
  idempotency_key  TEXT NOT NULL UNIQUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS one_confirmed_per_slot
  ON bookings(slot_id) WHERE status = 'confirmed';

CREATE TABLE IF NOT EXISTS messages (
  id          SERIAL PRIMARY KEY,
  session_id  TEXT NOT NULL,
  role        TEXT NOT NULL,
  content     JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS handoffs (
  id          SERIAL PRIMARY KEY,
  session_id  TEXT NOT NULL,
  reason      TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO slots (starts_at)
SELECT (d + make_interval(hours => h)) AT TIME ZONE 'Asia/Kolkata'
FROM generate_series(
       date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata') + interval '1 day',
       date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata') + interval '3 day',
       interval '1 day') AS d,
     generate_series(10, 17) AS h
ON CONFLICT DO NOTHING;
