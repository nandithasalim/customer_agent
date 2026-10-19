import sys
from agent import chat

sid = sys.argv[1] if len(sys.argv) > 1 else "me"
print(f"chatting as session '{sid}' (Ctrl+C to quit)")
while True:
    print("bot:", chat(sid, input("you: ")))
