import base64, io
from dotenv import load_dotenv
load_dotenv(override=True)
from fastapi import UploadFile, File, Form
from fastapi.responses import HTMLResponse
from openai import OpenAI
from main import app          # reuse the same app, so /chat still works
from agent import chat

client = OpenAI()


@app.get("/", response_class=HTMLResponse)
def home():
    return open("voice.html").read()


@app.post("/voice")
def voice(session_id: str = Form(...), audio: UploadFile = File(...)):
    data = audio.file.read()
    ext = "mp4" if "mp4" in (audio.content_type or "") else "webm"
    f = io.BytesIO(data)
    f.name = f"call.{ext}"

    heard = client.audio.transcriptions.create(
        model="whisper-1",
        file=f,
        prompt="Clinic appointment call. Phone numbers have 10 digits.",
    ).text

    if not heard.strip():
        reply = "Sorry, I didn't catch that. Could you say it again?"
    else:
        reply = chat(session_id, heard, channel="voice")

    speech = client.audio.speech.create(model="tts-1", voice="alloy", input=reply)
    return {
        "heard": heard,
        "reply": reply,
        "audio": base64.b64encode(speech.content).decode(),
    }
