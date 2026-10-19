from datetime import date, timedelta
from tools import list_slots

tomorrow = (date.today() + timedelta(days=1)).isoformat()
print(list_slots(tomorrow))