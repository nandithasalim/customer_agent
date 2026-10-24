import re


def clean_digits(text):
    """Merge spoken digit groups like '8127-8125-97' into '8127812597' (only if 10-12 digits)."""
    def fix(m):
        d = re.sub(r"\D", "", m.group(0))
        return d if 10 <= len(d) <= 12 else m.group(0)
    return re.sub(r"\d[\d\-\s,.]{7,}\d", fix, text)
