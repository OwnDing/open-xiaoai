#!/system/bin/sh
# Runs 小七电视助手 on the TV as the adb shell user (install.sh copies this to /data/local/tmp):
#   sh /data/local/tmp/xiaoqi-tv-helper.sh [start|stop|restart|status]
# start (the default) does nothing when it is already running, so callers may run it before
# every use; a real reboot of the TV ends the helper, standby does not.
DIR=/data/local/tmp
NAME=xiaoqi-tv-helper

running() {
    pidof "$NAME" >/dev/null
}

start() {
    running && return 0
    CLASSPATH="$DIR/$NAME.apk" setsid app_process /system/bin --nice-name="$NAME" \
        com.openxiaoai.tvhelper.Main "$DIR/$NAME.token" >"$DIR/$NAME.log" 2>&1 </dev/null &
    # setsid forks and the name only changes once the VM is up, so watch the log instead.
    for _ in $(seq 1 40); do
        grep -q "listening on" "$DIR/$NAME.log" 2>/dev/null && return 0
        grep -q "Exception\|usage:" "$DIR/$NAME.log" 2>/dev/null && break
        sleep 0.5
    done
    cat "$DIR/$NAME.log" >&2
    return 1
}

stop() {
    pid="$(pidof "$NAME")" && kill $pid
    while running; do sleep 0.2; done
}

case "${1:-start}" in
    start) start ;;
    stop) stop ;;
    restart) stop; start ;;
    status) running && echo running || { echo stopped; exit 1; } ;;
    *) echo "usage: $0 [start|stop|restart|status]" >&2; exit 2 ;;
esac
