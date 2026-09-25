#!/bin/sh
# SVG を PNG に (ヘッドレス Chromium, 幅いっぱいに拡大)。 usage: svg2png.sh in.svg out.png width height
CHROME=${CHROME:-/opt/pw-browsers/chromium-1194/chrome-linux/chrome}
SVG=$(readlink -f "$1")
HTML=$(mktemp --suffix=.html)
printf '<html><body style="margin:0;background:#fff"><img src="file://%s" style="width:100vw;height:100vh;object-fit:contain;display:block"></body></html>' "$SVG" > "$HTML"
"$CHROME" --headless=new --no-sandbox --disable-gpu --hide-scrollbars --allow-file-access-from-files \
  --default-background-color=ffffffff --window-size="$3,$4" --screenshot="$2" "file://$HTML" >/dev/null 2>&1
rm -f "$HTML"
