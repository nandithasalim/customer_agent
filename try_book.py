from tools import list_slots, book_slot
from datetime import date, timedelta

tomorrow = (date.today() + timedelta(days=1)).isoformat()
result = list_slots(tomorrow)
print(result)                      # see the real shape once
slot_id = result["slots"][0]["slot_id"]

print("1st  :", book_slot("chat-A", slot_id, "Anu", "9999900000"))
print("retry:", book_slot("chat-A", slot_id, "Anu", "9999900000"))
print("other:", book_slot("chat-B", slot_id, "Ravi", "8888800000"))