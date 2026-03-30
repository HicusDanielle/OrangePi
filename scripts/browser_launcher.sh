#!/bin/bash
# Launch Firefox in fullscreen kiosk mode pointing at the dashboard
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/0
sleep 3

# Wait for dashboard to be ready (up to 10s)
for i in {1..10}; do
  if curl -s http://localhost:5004 > /dev/null 2>&1; then
    break
  fi
  sleep 1
done

LANDING_PAGE="${LANDING_PAGE:-http://localhost:5004}"
/usr/bin/firefox --kiosk --new-instance --width=1024 --height=600 "$LANDING_PAGE" &
wait
