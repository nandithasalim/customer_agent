import time
from dotenv import load_dotenv
from openai import OpenAI
from agent import chat

load_dotenv(override=True)
client = OpenAI()

persona = ("You are Anu Nair, phone 9847012345. You want an appointment tomorrow afternoon. "
           "Reply with only your next chat message, one sentence. "
           "When your booking is confirmed, reply exactly: DONE")
msg = "Hi, I'd like an appointment tomorrow afternoon."
sid = f"bench-mini-{int(time.time())}"

fake = [{"role": "system", "content": persona},
        {"role": "assistant", "content": msg}]      # what the fake customer already said

for turn in range(8):
    print("CUSTOMER:", msg)
    bot = chat(sid, msg)                            # same function talk.py calls
    print("BOT     :", bot, "\n")
    fake.append({"role": "user", "content": bot})   # the fake customer "hears" the bot
    msg = client.chat.completions.create(model="gpt-4o-mini", messages=fake).choices[0].message.content
    fake.append({"role": "assistant", "content": msg})
    if "DONE" in msg:
        break
