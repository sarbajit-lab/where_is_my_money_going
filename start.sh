#!/usr/bin/env bash
# Start WIMMG and open it in the browser.
# Usage: ./start.sh            (port 5000)
#        ./start.sh --port 5050
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then exec "$py" run.py --open "$@"; fi
done
echo "Python 3.10 or newer is needed: https://www.python.org/downloads/" >&2
exit 1
