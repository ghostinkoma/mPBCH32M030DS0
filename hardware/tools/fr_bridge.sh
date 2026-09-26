#!/bin/sh
# Freerouting 中継 (ホスト側で常駐): chroot 内の KiCad 8 から書かれた *.frreq を見つけて Freerouting を実行する。
#   usage: tools/fr_bridge.sh <repo-root>
ROOT=$(readlink -f "$1")
JAR=$(dirname "$(readlink -f "$0")")/freerouting-1.9.0.jar
while true; do
  for req in $(find "$ROOT" -name "*.frreq" 2>/dev/null); do
    dir=$(dirname "$req")
    set -- $(cat "$req")          # [@jar] dsn ses passes [opts...]
    jar=$JAR
    case "$1" in @*) jar=$(dirname "$JAR")/${1#@}; shift;; esac
    dsn=$1; ses=$2; passes=$3; shift 3
    rm -f "$req"
    (cd "$dir" && xvfb-run -a java -jar "$jar" -de "$dsn" -do "$ses" -mp "$passes" "$@" > "$dsn.frlog" 2>&1; touch "$ses.frdone") &   # 複数基板を並列に配線
  done
  sleep 2
done
