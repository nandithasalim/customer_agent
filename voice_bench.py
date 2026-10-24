import io, random, sys, time
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
load_dotenv(override=True)
from openai import OpenAI
from agent import chat
from voice_utils import clean_digits
from db import connect

client = OpenAI()
VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
WORDS = "zero one two three four five six seven eight nine".split()


def say_number(num):
    words = [WORDS[int(d)] for d in num]
    if random.random() < 0.5:                       # "98470, 12345" style
        return " ".join(words[:5]) + ", " + " ".join(words[5:])
    return " ".join(words)


def speak_and_hear(text, voice, speed):
    audio = client.audio.speech.create(model="tts-1", voice=voice, input=text, speed=speed).content
    f = io.BytesIO(audio); f.name = "call.mp3"
    return client.audio.transcriptions.create(
        model="whisper-1", file=f,
        prompt="Clinic appointment call. Phone numbers have 10 digits.").text


def trial(i):
    num = random.choice("6789") + "".join(random.choice("0123456789") for _ in range(9))
    voice, speed = random.choice(VOICES), random.choice([0.9, 1.0, 1.2, 1.4])
    sid = f"bench-vb-{int(time.time())}-{i}"
    lines = [
        "Hi, I need an appointment tomorrow afternoon.",
        f"My name is Anu Nair and my number is {say_number(num)}.",
        "Yes, that's right.",
        "The earliest time you offered, please.",
        "Yes, please book it.",
        "Yes.",
    ]
    heard_num_ok = None
    log = []
    for k, line in enumerate(lines):
        heard = speak_and_hear(line, voice, speed)
        if k == 1:
            heard_num_ok = num in "".join(c for c in heard if c.isdigit())
        rep = chat(sid, clean_digits(heard), channel="voice")
        log.append((heard, rep))

    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE idempotency_key LIKE %s AND status='confirmed'",
            (sid + "%",)).fetchall()
    if not rows:
        outcome = "no_booking"
    elif any(num in str(v) for r in rows for v in r.values()):
        outcome = "correct"
    else:
        outcome = "WRONG_PHONE"
    return {"i": i, "num": num, "voice": voice, "speed": speed,
            "whisper_ok": heard_num_ok, "outcome": outcome, "log": log}


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    try:
        from bench import cleanup
        cleanup()
    except Exception as e:
        print('cleanup skipped:', e)
    with ThreadPoolExecutor(1) as ex:               # small waves so slots don't run out
        res = list(ex.map(trial, range(n)))
    for r in res:
        print({k: v for k, v in r.items() if k != 'log'})
        if r['outcome'] != 'correct':
            for h, a in r['log']:
                print('   CALLER:', h, '\n   AGENT :', a)
    w = sum(r["whisper_ok"] for r in res)
    print(f"\nWhisper got the number right: {w}/{n}")
    for o in ("correct", "no_booking", "WRONG_PHONE"):
        print(f"{o}: {sum(r['outcome'] == o for r in res)}/{n}")
    try:
        from bench import cleanup
        cleanup()
    except Exception as e:
        print("cleanup skipped:", e)
