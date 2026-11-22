#!/bin/bash
# Fast option: wait for every 2nd cut-out frame, stop the cut-out, then export.
cd /home/user/Edit
need=$(ls work/small | awk 'NR%2==1' | sed 's/jpg$/png/')
while :; do
  missing=0; for n in $need; do [ -f work/masks/$n ] || { missing=1; break; }; done
  [ $missing = 0 ] && break; sleep 30
done
pkill -f tools/cutout.py; sleep 2; rm -f work/masks/*.tmp.png
echo "CUTOUT HALF DONE, exporting"
.venv/bin/python tools/render.py work/config.json && echo "EXPORT DONE" || echo "EXPORT FAILED"
