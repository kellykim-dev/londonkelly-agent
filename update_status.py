import json, sys
from datetime import datetime

now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
agent = sys.argv[1] if len(sys.argv) > 1 else "weekly_report"

try:
    with open('status.json', 'r') as f:
        data = json.load(f)
except:
    data = {}

data[agent] = {'status': 'done', 'last_run': now}

with open('status.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f"✅ {agent} = done")
