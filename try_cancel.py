from tools import list_slots, book_slot, cancel_booking, handoff_to_human
from datetime import date, timedelta

tomorrow = (date.today() + timedelta(days=1)).isoformat()
slot_id = list_slots(tomorrow)["slots"][0]["slot_id"]
print("slot:", slot_id)

b = book_slot("chat-C", slot_id, "Meera", "7777700000")
print("book       :", b)
bid = b["booking_id"]

print("wrong chat :", cancel_booking("chat-X", bid))
print("cancel     :", cancel_booking("chat-C", bid))
print("cancel again:", cancel_booking("chat-C", bid))

free = [s["slot_id"] for s in list_slots(tomorrow)["slots"]]
print("slot free again?", slot_id in free)

print("other books:", book_slot("chat-D", slot_id, "Arjun", "6666600000"))
print("handoff    :", handoff_to_human("chat-E", "chest pain, wants to talk to a doctor"))