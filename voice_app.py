"""The web app: demo page at /, text chat at /chat (from main.py), voice at /voice,
button/typed turns on the voice page at /say, and speech for a reply at /tts.

Run locally:   uvicorn voice_app:app --port 8000
On a host:     uvicorn voice_app:app --host 0.0.0.0 --port $PORT
"""
import io, json, os, re, threading, time
T = time.perf_counter
from collections import defaultdict, deque

from dotenv import load_dotenv
load_dotenv(override=True)
from fastapi import File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from openai import OpenAI
from pydantic import BaseModel

from main import app          # reuse the same app, so /chat still works
from agent import chat, load_history
from db import connect
from voice_utils import clean_digits

client = OpenAI()

# ---------- limits, so a public link can't burn the OpenAI budget ----------
PER_IP_PER_HOUR = int(os.getenv("PER_IP_PER_HOUR", "80"))     # requests per visitor per hour (a voice turn is 2: reply + speech)
GLOBAL_PER_DAY = int(os.getenv("GLOBAL_PER_DAY", "800"))      # requests for the whole site per day
MAX_BODY = {"/chat": 5_000, "/say": 5_000, "/tts": 5_000, "/voice": 3_000_000}   # bytes; 3 MB is about a minute of audio

_hits = defaultdict(deque)
_day = {"date": None, "n": 0}
_lock = threading.Lock()


def _too_many(msg):
    return JSONResponse({"error": "rate_limited", "message": msg}, status_code=429)


@app.middleware("http")
async def limits(request: Request, call_next):
    path = request.url.path
    if request.method == "POST" and path in MAX_BODY:
        size = int(request.headers.get("content-length") or 0)
        if size > MAX_BODY[path]:
            return JSONResponse({"error": "too_large", "message": "That message is too long. Keep voice turns under a minute."},
                                status_code=413)
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
        now, today = time.time(), time.strftime("%Y-%m-%d")
        new_day = False
        with _lock:
            if _day["date"] != today:
                _day.update(date=today, n=0)
                new_day = True
            q = _hits[ip]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= PER_IP_PER_HOUR:
                return _too_many("You've reached this demo's hourly limit. Please try again in an hour.")
            if _day["n"] >= GLOBAL_PER_DAY:
                return _too_many("The demo has reached its daily limit. Please try again tomorrow.")
            q.append(now)
            _day["n"] += 1
        if new_day:
            threading.Thread(target=purge_old_demo_calls, daemon=True).start()
    return await call_next(request)


# lets a separately hosted frontend call this API from the browser
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- database setup and cleanup ----------
def purge_old_demo_calls():
    """Delete website calls (session ids starting with web-) older than a day, and free their slots."""
    try:
        with connect() as conn:
            conn.execute("UPDATE slots SET is_booked = FALSE WHERE id IN (SELECT slot_id FROM bookings "
                         "WHERE idempotency_key LIKE 'web-%' AND status = 'confirmed' AND created_at < now() - interval '1 day')")
            conn.execute("DELETE FROM bookings WHERE idempotency_key LIKE 'web-%' AND created_at < now() - interval '1 day'")
            conn.execute("DELETE FROM messages WHERE session_id LIKE 'web-%' AND created_at < now() - interval '1 day'")
            conn.execute("DELETE FROM handoffs WHERE session_id LIKE 'web-%' AND created_at < now() - interval '1 day'")
    except Exception as e:
        print("purge failed:", e)


@app.on_event("startup")
def setup_database():
    """Create tables if missing and keep 30 days of future slots. Safe to run on every start."""
    try:
        with connect() as conn:
            conn.execute(open("schema.sql").read())
            conn.execute(open("seed_slots.sql").read())
        purge_old_demo_calls()
        print("database ready")
    except Exception as e:
        print("database setup failed:", e)


# ---------- quick replies: buttons the caller can tap instead of speaking ----------
YES_NO = re.compile(r"(is that (right|correct|ok|okay)|shall i|should i|would you like (me )?to|do you want (me )?to|can i go ahead|do you confirm)[^?]*\?\s*$", re.I)
HOUR_WORDS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]


def _time_mentioned(reply, h, m):
    """Does the reply mention this clock time, in digits ('2:30', '2 PM') or words ('two thirty')?"""
    w = HOUR_WORDS[h]
    if m == 30:
        pats = [rf"\b{h}[:.]30\b", rf"\b{w}[\s-]thirty\b", rf"\bhalf past {w}\b"]
    elif m == 0:
        pats = [rf"\b{h}(:00)?\s*(a\.?m|p\.?m|o'?\s?clock)", rf"\b{h}:00\b",
                rf"\b{w}\s+(o'?\s?clock|in the|a\.?m|p\.?m)",
                rf"\b({w}|{h})\b(?=\s*(,|and\b|or\b))"]   # an hour in a list: "three, and four in the afternoon"
        if h == 12:
            pats.append(r"\bnoon\b")
    else:
        pats = [rf"\b{h}[:.]{m:02d}\b"]
    return any(re.search(p, reply, re.I) for p in pats)


def quick_options(session_id, reply):
    """Yes/No for confirmation questions; real free slots the reply offered, as time buttons."""
    reply = (reply or "").strip()
    if not reply.endswith("?"):
        return []
    if YES_NO.search(reply):
        return ["Yes", "No"]
    slots = []                                   # list_slots results from this turn only
    for msg in reversed(load_history(session_id)):
        if msg.get("role") == "user":
            break
        if msg.get("role") == "tool":
            try:
                data = json.loads(msg.get("content") or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(data, dict) and isinstance(data.get("slots"), list):
                slots = data["slots"] + slots
    labels = []
    for slot in slots:
        mt = re.match(r"(\d{1,2}):(\d{2}) (AM|PM)", slot.get("time", ""))
        if not mt:
            continue
        h, m, ap = int(mt.group(1)), int(mt.group(2)), mt.group(3)
        label = f"{h}:{m:02d} {ap}"
        if label not in labels and _time_mentioned(reply, h, m):
            labels.append(label)
    return labels[:4]


# ---------- routes ----------
@app.get("/", response_class=HTMLResponse)
def home():
    return open("voice.html").read()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/voice")
def voice(session_id: str = Form(...), audio: UploadFile = File(...)):
    t0 = T()
    data = audio.file.read()
    ext = "mp4" if "mp4" in (audio.content_type or "") else "webm"
    f = io.BytesIO(data)
    f.name = f"call.{ext}"

    heard = client.audio.transcriptions.create(
        model="whisper-1",
        file=f,
        prompt="Clinic appointment call. Phone numbers have 10 digits.",
    ).text

    t1 = T()
    if not heard.strip():
        reply = "Sorry, I didn't catch that. Could you say it again?"
    else:
        reply = chat(session_id, clean_digits(heard), channel="voice")

    options = quick_options(session_id, reply)
    t2 = T()
    print(f"TIMING voice whisper={t1-t0:.1f}s agent={t2-t1:.1f}s text-ready={t2-t0:.1f}s", flush=True)
    return {"heard": heard, "reply": reply, "options": options}


class SayIn(BaseModel):
    session_id: str
    message: str


@app.post("/say")
def say(body: SayIn):
    """A typed message or a tapped quick reply on the voice page: same agent, voice rules, no speech-to-text."""
    t0 = T()
    reply = chat(body.session_id, clean_digits(body.message), channel="voice")
    options = quick_options(body.session_id, reply)
    print(f"TIMING say agent={T()-t0:.1f}s", flush=True)
    return {"reply": reply, "options": options}


class TtsIn(BaseModel):
    text: str


@app.post("/tts")
def tts(body: TtsIn):
    """Speech for a reply the page already shows, fetched separately so the text appears first."""
    text = body.text.strip()[:600]
    if not text:
        return Response(status_code=204)
    t0 = T()
    audio = client.audio.speech.create(model="tts-1", voice="alloy", input=text).content
    print(f"TIMING tts={T()-t0:.1f}s", flush=True)
    return Response(content=audio, media_type="audio/mpeg")
