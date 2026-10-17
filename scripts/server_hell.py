"""server_hell: keep the free Render instance awake by pinging it every few minutes.

Run:  python scripts/server_hell.py            (default URL, every 240 s)
      python scripts/server_hell.py URL 180    (custom URL and interval)
Stop with Ctrl+C. Uses only the standard library.
"""
import sys
import time
import urllib.request
from datetime import datetime

URL = sys.argv[1] if len(sys.argv) > 1 else "https://hound-99l2.onrender.com"
INTERVAL = int(sys.argv[2]) if len(sys.argv) > 2 else 240

while True:
    stamp = datetime.now().strftime("%H:%M:%S")
    try:
        with urllib.request.urlopen(f"{URL.rstrip('/')}/api/status", timeout=90) as r:
            print(f"{stamp}  {r.status}  awake", flush=True)
    except Exception as exc:
        print(f"{stamp}  failed: {exc}", flush=True)
    time.sleep(INTERVAL)
