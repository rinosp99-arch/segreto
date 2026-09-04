#!/usr/bin/env bash
set -e
MED=/app/frontend/public/media
mkdir -p "$MED" /tmp/clipsrc
cd /tmp/clipsrc

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

declare -A SRC=(
  [pub1]="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=900&q=80"
  [pub2]="https://images.unsplash.com/photo-1517841905240-472988babdf9?w=900&q=80"
  [pub3]="https://images.unsplash.com/photo-1519699047748-de8e457a634e?w=900&q=80"
  [pub4]="https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=900&q=80"
  [sec1]="https://images.pexels.com/photos/1631181/pexels-photo-1631181.jpeg?auto=compress&cs=tinysrgb&w=900"
  [sec2]="https://images.pexels.com/photos/6311392/pexels-photo-6311392.jpeg?auto=compress&cs=tinysrgb&w=900"
  [sec3]="https://images.pexels.com/photos/6976094/pexels-photo-6976094.jpeg?auto=compress&cs=tinysrgb&w=900"
  [sec4]="https://images.pexels.com/photos/2065195/pexels-photo-2065195.jpeg?auto=compress&cs=tinysrgb&w=900"
)

for key in "${!SRC[@]}"; do
  curl -s -A "$UA" -L --max-time 30 -o "$key.jpg" "${SRC[$key]}"
  # subtle vertical ken-burns clip, 6s, small size
  ffmpeg -y -loop 1 -i "$key.jpg" -t 6 -r 25 \
    -vf "scale=1080:-2,crop=iw:'min(ih,iw*16/9)',zoompan=z='min(zoom+0.0007,1.18)':d=150:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=720x1280,format=yuv420p" \
    -c:v libx264 -preset veryfast -crf 31 -an -movflags +faststart "$MED/$key.mp4" >/dev/null 2>&1
  # poster frame
  ffmpeg -y -i "$MED/$key.mp4" -frames:v 1 -q:v 4 "$MED/$key.jpg" >/dev/null 2>&1
  echo "done $key"
done
ls -la "$MED"
