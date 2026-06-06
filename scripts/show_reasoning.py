import json, glob
logs = sorted(glob.glob('logs_download/interactions/heavyweight_*.jsonl'))
with open(logs[-1], encoding='utf-8') as f:
    for line in f:
        entry = json.loads(line)
        r = entry.get('round')
        rc = entry.get('reasoning_content', '')
        if rc:
            print(f'=== Round {r} ({len(rc)} chars) ===')
            print(rc[:600])
            print()
