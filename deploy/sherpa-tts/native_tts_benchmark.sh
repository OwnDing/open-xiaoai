#!/bin/sh

set -e

. /usr/share/libubox/jshn.sh

now_ms() {
    awk '{ printf "%.0f\n", $1 * 1000 }' /proc/uptime
}

run_case() {
    label="$1"
    expected_chars="$2"
    text="$3"
    output_path="/tmp/open-xiaoai-native-tts-bench-${label}.audio"

    json_init
    json_add_string text "$text"
    json_add_int save 1
    payload="$(json_dump)"
    json_cleanup

    started_ms="$(now_ms)"
    response="$(ubus call mibrain text_to_speech "$payload")"
    finished_ms="$(now_ms)"

    json_init
    json_load "$response"
    json_get_var info info
    json_cleanup

    json_init
    json_load "$info"
    json_get_var generated_path path
    json_cleanup

    if [ -z "$generated_path" ] || [ ! -f "$generated_path" ]; then
        echo "ERROR label=$label response=$response" >&2
        exit 1
    fi

    mv "$generated_path" "$output_path"
    size_bytes="$(wc -c < "$output_path" | tr -d ' ')"
    elapsed_ms=$((finished_ms - started_ms))

    echo "RESULT label=$label chars=$expected_chars elapsed_ms=$elapsed_ms bytes=$size_bytes path=$output_path"
}

short_text='你好小七，请用自然流畅的声音回答我的问题。'
medium_text='你好小七，请用自然流畅的声音回答我的问题。今天天气不错，适合出门散步。请顺便告诉我今天需要注意什么。也请提醒我带好雨伞。'
long_text='你好小七，请用自然流畅的声音回答我的问题。今天天气不错，适合出门散步。请顺便告诉我今天需要注意什么。然后给我安排一个简单的下午计划，包括工作、休息和运动。回答时语速自然一些，不要太快，也不要在句子之间停顿太久。最后再用一句话总结你的建议。'

run_case short_a 21 "$short_text"
run_case short_b 21 "$short_text"
run_case medium 60 "$medium_text"
run_case long 119 "$long_text"
