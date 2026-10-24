-- 30 days of half-hour slots, 09:00-19:30 IST (the bench needs more than schema.sql seeds)
INSERT INTO slots (starts_at)
SELECT (d + make_interval(hours => h, mins => m)) AT TIME ZONE 'Asia/Kolkata'
FROM generate_series(date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata'),
     date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata') + interval '30 day', interval '1 day') AS d,
     generate_series(9, 19) AS h, (VALUES (0), (30)) AS v(m)
ON CONFLICT DO NOTHING;
