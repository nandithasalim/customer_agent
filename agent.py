import json
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from openai import OpenAI
from psycopg.types.json import Jsonb
from db import connect
from tools import list_slots, book_slot, cancel_booking, handoff_to_human

load_dotenv()
client = OpenAI()
MODEL = "gpt-4o-mini"
MAX_STEPS = 6


def system_prompt():
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    return f"""You are the appointment assistant for Lakeside Clinic, Kochi.
Today is {now:%A %d %B %Y}, current time {now:%I:%M %p} IST.

Rules:
- EMERGENCY (chest pain, trouble breathing, heavy bleeding, fainting, stroke signs, severe injury, thoughts of self-harm): in your VERY FIRST reply, call handoff_to_human AND tell the customer to call 112 (or 108 for an ambulance) immediately. Never offer an appointment. Never say 'stay on the line' or promise when staff will respond.
- ONLY offer appointment times returned by the list_slots tool. Never invent a time.
- Before booking, confirm the customer's name, phone number and the exact slot.
- Call book_slot only after the customer clearly says yes.
- If a booking fails because the slot is taken, say so and offer other slots.
- To cancel, you need the booking id from earlier in this chat.
- Call handoff_to_human for: medical emergencies or serious symptoms, complaints,
  payment or refund questions, anything you cannot do, or if the customer asks for a person.
  For emergencies also tell them to call emergency services right away.
- Never give medical advice. Keep replies short and friendly."""


TOOLS = [
    {"type": "function", "function": {
        "name": "list_slots",
        "description": "List free appointment slots on one day.",
        "parameters": {"type": "object",
                       "properties": {"day": {"type": "string", "description": "YYYY-MM-DD"}},
                       "required": ["day"]}}},
    {"type": "function", "function": {
        "name": "book_slot",
        "description": "Book a slot. Only after the customer confirmed name, phone and time.",
        "parameters": {"type": "object",
                       "properties": {"slot_id": {"type": "integer"},
                                      "name": {"type": "string"},
                                      "phone": {"type": "string"}},
                       "required": ["slot_id", "name", "phone"]}}},
    {"type": "function", "function": {
        "name": "cancel_booking",
        "description": "Cancel a booking made in this chat.",
        "parameters": {"type": "object",
                       "properties": {"booking_id": {"type": "integer"}},
                       "required": ["booking_id"]}}},
    {"type": "function", "function": {
        "name": "handoff_to_human",
        "description": "Pass the customer to a human staff member.",
        "parameters": {"type": "object",
                       "properties": {"reason": {"type": "string"}},
                       "required": ["reason"]}}},
]


def run_tool(session_id, name, args):
    # session_id comes from US, never from the model
    try:
        if name == "list_slots":
            return list_slots(args["day"])
        if name == "book_slot":
            return book_slot(session_id, args["slot_id"], args["name"], args["phone"])
        if name == "cancel_booking":
            return cancel_booking(session_id, args["booking_id"])
        if name == "handoff_to_human":
            return handoff_to_human(session_id, args["reason"])
        return {"ok": False, "error": f"unknown tool {name}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def load_history(session_id):
    with connect() as conn:
        rows = conn.execute(
            "SELECT content FROM messages WHERE session_id = %s ORDER BY id",
            (session_id,),
        ).fetchall()
    return [r["content"] for r in rows]


def save(session_id, msg):
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
            (session_id, msg["role"], Jsonb(msg)),
        )


def chat(session_id: str, user_text: str) -> str:
    history = load_history(session_id)

    def add(m):
        history.append(m)
        save(session_id, m)

    add({"role": "user", "content": user_text})

    for _ in range(MAX_STEPS):
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system_prompt()}] + history,
            tools=TOOLS,
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:                      # plain answer -> done
            add({"role": "assistant", "content": msg.content})
            return msg.content

        add({"role": "assistant", "content": msg.content,
             "tool_calls": [{"id": tc.id, "type": "function",
                             "function": {"name": tc.function.name,
                                          "arguments": tc.function.arguments}}
                            for tc in msg.tool_calls]})

        for tc in msg.tool_calls:                   # run every tool it asked for
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = run_tool(session_id, tc.function.name, args)
            add({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

    # too many steps -> give up safely
    handoff_to_human(session_id, "agent exceeded max steps")
    fallback = "Sorry, I'm having trouble. A staff member will call you back shortly."
    add({"role": "assistant", "content": fallback})
    return fallback
