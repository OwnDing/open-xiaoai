#!/usr/bin/env bash
# Copies 小七电视助手 to the TV over WiFi adb and (re)starts it:
#   ./install.sh [tv-address] [token]
# tv-address defaults to 192.168.5.9:5555; the token defaults to $TV_HELPER_TOKEN, else a new
# random one, printed at the end (Hermes needs the same value in .env as TV_HELPER_TOKEN).
# Nothing is installed as an app: TCL rejects adb installs and freezes background apps.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TV="${1:-192.168.5.9:5555}"
TOKEN="${2:-${TV_HELPER_TOKEN:-$(openssl rand -hex 16)}}"
DIR=/data/local/tmp
NAME=xiaoqi-tv-helper
APK="$HERE/app/build/outputs/apk/debug/app-debug.apk"

(cd "$HERE" && ./gradlew -q assembleDebug)

adb connect "$TV" >/dev/null
export ANDROID_SERIAL="$TV"
if [ "$(adb get-state 2>/dev/null)" != device ]; then
    echo "电视 $TV 没连上：确认电视开着，第一次连接要在电视上点“允许 USB 调试”。" >&2
    exit 1
fi

adb push "$APK" "$DIR/$NAME.apk" >/dev/null
adb push "$HERE/tv-helper.sh" "$DIR/$NAME.sh" >/dev/null
printf '%s\n' "$TOKEN" | adb shell "umask 077; cat > $DIR/$NAME.token"
adb shell sh "$DIR/$NAME.sh" restart

host="${TV%%:*}"
curl -sf -m 5 -H "Authorization: Bearer $TOKEN" "http://$host:8765/status"
echo
echo "TV_HELPER_URL=http://$host:8765"
echo "TV_HELPER_TOKEN=$TOKEN"
