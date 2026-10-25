# customer_agent: an AI appointment assistant, and a bench that tests it

A chat agent for a (fictional) clinic, Lakeside Clinic, Kochi. It books and cancels appointments through tool calls (gpt-4o-mini) on Postgres, and hands over to a human when it should. A test bench plays 16 kinds of simulated customers against it and reports what breaks.

## Results

Same bench, same 16 customer types x 5 runs = 80 simulated chats per column.

| | Before fixes | After fixes |
|---|---|---|
| Chats handled correctly | 54/80 (67%) | **78/80 (97%)** |
| Slot integrity mismatches (free slot with a booking, or booked slot without one) | 0 | 0 |

Pass/fail counts only checks that code can verify (database state, handoff counts, phone validity). An LLM also reviews each chat, but its notes are advisory and do not change the score.

## What the bench found, and what I changed

| Problem found | Fix |
|---|---|
| Up to 14 handoff tickets created for a single chat | One handoff per chat, enforced in the tool (`handoff_to_human` is idempotent) |
| Bookings saved with an empty or fake phone (`''`, `555-1234`) | `book_slot` validates a 10-digit Indian mobile number |
| A hacker persona bulk-booked 4 slots; a customer who changed their mind got 2 bookings | One active booking per chat, enforced in `book_slot` |
| Normal booking customers (e.g. asking about medicine) were handed to staff | Prompt: decline medical advice, keep booking, do not hand off |
| Bot kept booking after handing off | Code guard: after a handoff, `book_slot` and `cancel_booking` are refused |
| Slow, inconsistent escalation of emergencies; booking without asking "Shall I book it?" | Prompt rules: hand off in the first reply and tell the customer to call 112/108; confirm before booking |

## How booking stays correct under concurrency

- `book_slot` locks the slot row (`SELECT ... FOR UPDATE`) inside a transaction.
- An idempotency key (`session_id:slot_id`) makes repeated calls return the same booking.
- A partial unique index (`one confirmed booking per slot`) is a last line of defence in Postgres.
- `race_test.py`: 20 customers booking the same slot at the same moment gave exactly 1 booking and 19 "taken". 10 simultaneous retries from one chat gave exactly 1 booking.

## How the bench works

1. `personas.py`: 16 customer types (happy path, vague, rude, changes their mind, cancels, emergency, complaint, refund, wants a human, asks for medical advice, prompt injection, outside hours, past date, wrong phone number, one-word replies, Manglish, repeated "yes").
2. `bench.py`: a second LLM plays each customer and chats with the real agent for up to 14 turns, 8 chats at a time. Every chat uses real tools and a real database.
3. Checks per chat: did the right booking, cancellation or handoff happen, valid phone, at most one handoff, emergencies handled in the first reply, no instructions leaked. After the run, a slot-integrity check.
4. Output: `report_<label>.html` with a pass rate and every transcript, failures first.

## Test any agent: `genbench.py`

`bench.py` is the original bench: it imports this agent's code directly. `genbench.py` is the same idea without that link. It talks to an agent over HTTP (`POST` a message, read the JSON reply) and takes everything else from a suite file:

- `target`: the URL, the request body and the name of the reply field
- `personas`: the simulated customers and what each one wants
- SQL checks on the agent's database (e.g. "exactly one confirmed booking with this name and phone") and regex rules on what the agent said (e.g. "never mentions its hidden instructions")
- `invariants` that must hold after the whole run (no slot booked twice, no slot marked booked without a booking)

```bash
python3 genbench.py suites/clinic.yaml --label mytest --repeats 5       # this clinic agent
uvicorn faq_agent:app --app-dir examples --port 8001                    # a second agent, no database
python3 genbench.py suites/faq.yaml --label faq --repeats 3             # checks only what it says
```

To test your own agent, copy `suites/clinic.yaml` and change the target, the personas and the SQL. `genbench.py` exits with code 1 when the pass rate is below `--min-pass` or an invariant fails, so it can gate a deploy.

## CI: a regression gate

`.github/workflows/bench.yml` runs on every pull request that touches the agent, its tools, the schema or the bench: it starts Postgres, runs the concurrency test (no LLM), starts the agent, and runs 18 simulated chats. The build fails if the pass rate is under 80%, any invariant breaks, or the concurrency test finds a double booking. A manual run (Actions tab > agent-bench > Run workflow) does 5 runs per customer type with a 90% gate. It needs an `OPENAI_API_KEY` repository secret. A pull-request run costs a few rupees of API usage.

## Known limitations

- Customers are LLM-simulated, so the bench is a proxy for real users. 80 chats is a small sample (one chat is about 1.25 points).
- The 2 remaining failures in the main run were both Manglish chats. Reading them, one was a test problem (the fake customer asked for dates the database has no slots for) and the other had the agent answering in broken Malayalam. After tightening that persona (tomorrow, around 2 PM) and adding Hinglish and Tanglish customers, the unchanged agent handled 30/30 chats in the three languages (right slot, name and phone). The main 80-chat numbers above were measured with the earlier, looser Manglish persona. These are short code-mixed text messages written by an LLM, not real speech or real users.
- In an earlier run, one chat booked and handed off in the same turn for a medicine question despite the prompt rule. The prompt is not a hard guarantee; the code guards are.
- The clinic, its data and its customers are fictional. There is no real patient data.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install openai fastapi uvicorn python-dotenv "psycopg[binary]"
docker run --name pg -e POSTGRES_PASSWORD=dev -p 5432:5432 -d postgres
docker exec -i pg psql -U postgres < schema.sql        # seeds 3 days of slots
``` 
The bench needs more slots than `schema.sql` seeds. Add 30 days:
```bash
docker exec -i pg psql -U postgres -c "
INSERT INTO slots (starts_at)
SELECT (d + make_interval(hours => h, mins => m)) AT TIME ZONE 'Asia/Kolkata'
FROM generate_series(date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata'),
     date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata') + interval '30 day', interval '1 day') AS d,
     generate_series(9, 19) AS h, (VALUES (0), (30)) AS v(m)
ON CONFLICT DO NOTHING;"
```

```bash
python3 talk.py me                 # chat with the agent in the terminal
uvicorn main:app --reload          # POST /chat {"session_id": "...", "message": "..."}
python3 race_test.py               # concurrency test
python3 bench.py mylabel 5         # 16 customer types x 5 runs, writes report_mylabel.html
```
An 80-chat run uses a few million gpt-4o-mini tokens.

## Files

`schema.sql` tables and constraints | `tools.py` the four tools | `agent.py` the LLM tool-calling loop | `main.py` the API | `talk.py` terminal chat | `race_test.py` concurrency test | `personas.py`, `bench.py` the test bench | `final_runs.sh` the before/after measurement | `genbench.py`, `suites/` the agent-agnostic bench | `examples/faq_agent.py` a second agent | `voice_app.py`, `voice.html`, `voice_bench.py` the voice channel | `.github/workflows/bench.yml` the CI gate

## Voice channel
Browser mic page (`voice.html`, served by `voice_app.py`) -> Whisper -> the same agent with voice-specific prompt rules -> text-to-speech.
`voice_bench.py` simulates calls with synthetic speech (6 voices, 4 speeds, random phone numbers) and checks the number stored in the database.

- 30 simulated calls: 28 booked with the correct phone number, **0 booked with a wrong number**, 2 ended without a booking (see `voice_results.txt`).
- Whisper dropped a digit once in 30 calls (`8962339400` heard as `896-239-400`); the agent refused the 9-digit number instead of booking it.
- Bug found by this test: Whisper writes numbers like `8127-8125-97`, and the LLM counted the digits wrongly and rejected valid numbers. Fixed by merging digit groups in code and removing digit-counting from the prompt.
- Limits: clean synthetic audio only, no phone-line noise or accents; English only; the scripted caller does not stop after a successful booking, which caused one of the two no-booking calls.

## Voice channel
Browser mic page (`voice.html`, served by `voice_app.py`) -> Whisper -> the same agent with voice-specific prompt rules -> text-to-speech.
`voice_bench.py` simulates calls with synthetic speech (6 voices, 4 speeds, random phone numbers) and checks the number stored in the database.

- 30 simulated calls: 28 booked with the correct phone number, **0 booked with a wrong number**, 2 ended without a booking (see `voice_results.txt`).
- Whisper dropped a digit once in 30 calls (`8962339400` heard as `896-239-400`); the agent refused the 9-digit number instead of booking it.
- Bug found by this test: Whisper writes numbers like `8127-8125-97`, and the LLM counted the digits wrongly and rejected valid numbers. Fixed by merging digit groups in code and removing digit-counting from the prompt.
- Limits: clean synthetic audio only, no phone-line noise or accents; English only; the scripted caller does not stop after a successful booking, which caused one of the two no-booking calls.
