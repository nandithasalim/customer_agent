# customer_agent

An AI receptionist for a clinic that books appointments over chat, plus a test bench that throws dozens of simulated customers at it and reports exactly where it fails.

## Why

Customer-facing AI agents (support, booking, sales, collections) usually work in demos and fail with real customers. They double-book, invent times that don't exist, book without the customer's confirmation, or miss when to hand off to a human. This project builds a small agent and the tooling to find those failures.

## How it works

**Part A: the agent**
- FastAPI chat endpoint, with an LLM (`gpt-4o-mini`) using tool calls
- Tools: `list_slots`, `book_slot`, `cancel_booking`, `handoff_to_human`. The LLM can only touch data through these.
- Postgres as the source of truth for slots, bookings, conversation logs and handoffs
- Safe under concurrency:
  - an idempotency key per booking, so a repeated request returns the same booking
  - `SELECT … FOR UPDATE` row locking inside a transaction, so two customers can't take one slot
  - a partial unique index (one confirmed booking per slot) as a database-level safety net

**Part B: the test bench**
- Personas: simulated customers with goals and behaviour (confused, angry, code-mixed Malayalam/English, emergencies, prompt-injection attempts)
- A runner that plays many conversations at once
- A judge: hard checks against the database plus an LLM grader
- A report: success rate, failure types with example transcripts, latency and cost per conversation

## Status

- [x] Database schema (slots, bookings, messages, handoffs)
- [ ] Tools and concurrency test
- [ ] Agent loop and `/chat` endpoint
- [ ] Test bench: personas, runner, judge, report
- [ ] Voice layer

## Stack

Python · FastAPI · PostgreSQL · psycopg 3 · OpenAI API · Docker
