import json, os
files = sorted(os.listdir('outputs'), reverse=True)
with open(f"outputs/{files[0]}") as f:
    d = json.load(f)
print("Summary:")
for s in d.get('summary',[]):
    print(f"  [{type(s).__name__}] {s}")
print("\nSensors:")
for i in d.get('sensor_panel',[]):
    print(f"  {i.get('label','')}: {i.get('value','')}")
