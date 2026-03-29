import json
import io

with io.open("out.txt", "rb") as f:
    raw = f.read()
    if raw.startswith(b'\xff\xfe'):
        text = raw.decode("utf-16le")
    else:
        text = raw.decode("utf-8")

data = json.loads(text)
collections = data.get("collections", [])
total = 0
missing = 0
for c in collections:
    items = c.get('items', [])
    total += len(items)
    for i in items:
        if i.get('missing'):
            missing += 1

print(f"Total maps in collections: {total}")
print(f"Missing maps (not in Realm Beatmap): {missing}")
