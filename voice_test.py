import subprocess, time
from dotenv import load_dotenv
from openai import OpenAI
from agent import chat

load_dotenv(override=True)
client = OpenAI()


def speak(text, path, voice):                      # text -> speech (mp3 file)
    with client.audio.speech.with_streaming_response.create(
            model="tts-1", voice=voice, input=text) as r:
        r.stream_to_file(path)


def listen(path):                                  # speech (mp3 file) -> text
    with open(path, "rb") as f:
        return client.audio.transcriptions.create(model="whisper-1", file=f).text


sid = f"bench-voice-{int(time.time())}"
caller_lines = [
    "Hi, I need an appointment tomorrow afternoon.",
    "Two thirty please. I'm Anu Nair, my number is nine eight four seven zero one two three four five.",
    "Yes, please book it.",
]

for line in caller_lines:
    speak(line, "caller.mp3", "echo")              # the pretend caller speaks
    heard = listen("caller.mp3")                   # the agent "hears" it
    reply = chat(sid, heard, channel="voice")                       # same agent as before
    speak(reply, "agent.mp3", "alloy")             # the agent speaks
    print("CALLER said :", line)
    print("AGENT heard :", heard)
    print("AGENT reply :", reply, "\n")
    subprocess.run(["afplay", "agent.mp3"])        # plays the reply on your Mac
