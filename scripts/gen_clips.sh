#!/usr/bin/env bash
# Generate seamless ~12s vertical teaser clips for the HOME "IN MOVIMENTO" film strip.
# Technique: render a gentle 6s Ken-Burns zoom-in, then boomerang (forward + reversed)
# to produce a ~12s clip that starts and ends on the SAME frame => seamless loop, no jump.
set -e
MED=/app/frontend/public/media
TMP=/tmp/clipsrc
mkdir -p "$MED" "$TMP"
cd "$TMP"

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

declare -A SRC=(
  [pub1]="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=1000&q=80"
  [pub2]="https://images.unsplash.com/photo-1517841905240-472988babdf9?w=1000&q=80"
  [pub3]="https://images.unsplash.com/photo-1519699047748-de8e457a634e?w=1000&q=80"
  [pub4]="https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=1000&q=80"
  [sec1]="https://images.pexels.com/photos/1631181/pexels-photo-1631181.jpeg?auto=compress&cs=tinysrgb&w=1000"
  [sec2]="https://images.pexels.com/photos/6311392/pexels-photo-6311392.jpeg?auto=compress&cs=tinysrgb&w=1000"
  [sec3]="https://images.pexels.com/photos/6976094/pexels-photo-6976094.jpeg?auto=compress&cs=tinysrgb&w=1000"
  [sec4]="https://images.pexels.com/photos/2065195/pexels-photo-2065195.jpeg?auto=compress&cs=tinysrgb&w=1000"
)

for key in "${!SRC[@]}"; do
  curl -s -A "$UA" -L --max-time 40 -o "$key.jpg" "${SRC[$key]}"
  # 6s gentle ken-burns zoom-in, vertical 720x1280
  ffmpeg -y -loop 1 -i "$key.jpg" -t 6 -r 25 \
    -vf "scale=1200:-2,crop=iw:'min(ih,iw*16/9)',zoompan=z='min(zoom+0.00045,1.14)':d=150:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=720x1280,format=yuv420p" \
    -c:v libx264 -preset veryfast -crf 30 -an -movflags +faststart "$TMP/${key}_fwd.mp4" >/dev/null 2>&1
  # reversed copy
  ffmpeg -y -i "$TMP/${key}_fwd.mp4" -vf reverse -an "$TMP/${key}_rev.mp4" >/dev/null 2>&1
  # concat fwd+rev => ~12s seamless boomerang
  ffmpeg -y -i "$TMP/${key}_fwd.mp4" -i "$TMP/${key}_rev.mp4" \
    -filter_complex "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v]" -map "[v]" \
    -c:v libx264 -preset veryfast -crf 30 -an -movflags +faststart "$MED/$key.mp4" >/dev/null 2>&1
  # poster frame (mid clip)
  ffmpeg -y -ss 1 -i "$MED/$key.mp4" -frames:v 1 -q:v 4 "$MED/$key.jpg" >/dev/null 2>&1
  echo "done $key"
done
echo "---durations---"
for f in "$MED"/*.mp4; do d=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$f"); echo "$f: $d"; done
ls -la "$MED"
