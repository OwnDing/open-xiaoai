//! Bounded, asynchronous diagnostics. File I/O never runs on the audio path.
use serde_json::{json, Value};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, LazyLock};
use std::time::{SystemTime, UNIX_EPOCH};

static DROPPED: AtomicU64 = AtomicU64::new(0);
static WRITER: LazyLock<mpsc::SyncSender<Value>> = LazyLock::new(|| {
    let (tx, rx) = mpsc::sync_channel::<Value>(128);
    std::thread::spawn(move || {
        let path = std::env::var("OPEN_XIAOAI_HEALTH_LOG")
            .unwrap_or_else(|_| "/data/open-xiaoai/logs/audio-health.jsonl".into());
        if let Some(parent) = std::path::Path::new(&path).parent() {
            let _ = fs::create_dir_all(parent);
        }
        let mut reported_error = false;
        for value in rx {
            let result = (|| -> std::io::Result<()> {
                if fs::metadata(&path)
                    .map(|m| m.len() >= 524_288)
                    .unwrap_or(false)
                {
                    let _ = fs::remove_file(format!("{path}.2"));
                    let _ = fs::rename(format!("{path}.1"), format!("{path}.2"));
                    fs::rename(&path, format!("{path}.1"))?;
                }
                let mut file = OpenOptions::new().create(true).append(true).open(&path)?;
                writeln!(file, "{}", value)
            })();
            if let Err(error) = result {
                DROPPED.fetch_add(1, Ordering::Relaxed);
                if !reported_error {
                    eprintln!("audio-health log unavailable: {error}");
                    reported_error = true;
                }
            } else {
                reported_error = false;
            }
        }
    });
    tx
});

pub fn unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

pub fn emit(event: &str, fields: Value) {
    let mut record = json!({"schema": 1, "role": "speaker", "event": event,
        "ts_ms": unix_ms(), "log_dropped_total": DROPPED.load(Ordering::Relaxed)});
    if let (Some(target), Some(source)) = (record.as_object_mut(), fields.as_object()) {
        target.extend(source.clone());
    }
    if WRITER.try_send(record).is_err() {
        DROPPED.fetch_add(1, Ordering::Relaxed);
    }
}
