use crate::utils::audio_health::{emit, unix_ms};
use serde_json::{json, Value};
use std::future::Future;
use std::process::Stdio;
use std::sync::Mutex as StdMutex;
use std::sync::{Arc, LazyLock};
use std::time::{Duration, Instant};
use tokio::io::{AsyncReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio::time::timeout;

use crate::base::AppError;

use super::config::{AudioConfig, AUDIO_CONFIG};

#[derive(PartialEq)]
enum State {
    Idle,
    Recording,
}

const A113_CAPTURE_BITS_PER_SAMPLE: u16 = 32;
const RECORD_READ_TIMEOUT: Duration = Duration::from_millis(500);
const MAX_CONSECUTIVE_READ_TIMEOUTS: usize = 10;

pub struct AudioRecorder {
    state: Arc<Mutex<State>>,
    arecord_thread: Arc<Mutex<Option<Child>>>,
    read_thread: Arc<Mutex<Option<JoinHandle<()>>>>,
}

static INSTANCE: LazyLock<AudioRecorder> = LazyLock::new(AudioRecorder::new);

impl AudioRecorder {
    fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(State::Idle)),
            arecord_thread: Arc::new(Mutex::new(None)),
            read_thread: Arc::new(Mutex::new(None)),
        }
    }

    pub fn instance() -> &'static Self {
        &INSTANCE
    }

    pub async fn stop_recording(&self) -> Result<(), AppError> {
        let mut state = self.state.lock().await;
        if *state == State::Idle {
            return Ok(());
        }

        if let Some(read_thread) = self.read_thread.lock().await.take() {
            read_thread.abort();
        }

        if let Some(mut arecord_thread) = self.arecord_thread.lock().await.take() {
            let _ = timeout(Duration::from_millis(100), arecord_thread.kill()).await;
        }

        *state = State::Idle;
        Ok(())
    }

    pub async fn start_recording<F, Fut>(
        &self,
        on_stream: F,
        config: Option<AudioConfig>,
    ) -> Result<(), AppError>
    where
        F: Fn(Vec<u8>, Value) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<(), AppError>> + Send + 'static,
    {
        let mut state = self.state.lock().await;
        if *state == State::Recording {
            return Ok(());
        }

        let requested_config = config.unwrap_or_else(|| (*AUDIO_CONFIG).clone());
        let capture_config = capture_config_for_recording(&requested_config);
        let mut arecord_thread = spawn_arecord(&capture_config)?;

        let mut stdout = arecord_thread.stdout.take().unwrap();
        let stderr = arecord_thread.stderr.take();
        let health = Arc::new(StdMutex::new(CaptureHealth::new(&requested_config)));
        let capture_id = health.lock().unwrap().capture_id.clone();
        emit(
            "capture_start",
            json!({"capture_id": capture_id,
            "sample_rate": requested_config.sample_rate, "capture_bits": capture_config.bits_per_sample,
            "wire_bits": requested_config.bits_per_sample, "channels": requested_config.channels}),
        );
        let weak = Arc::downgrade(&health);
        tokio::spawn(async move {
            let mut tick = tokio::time::interval(Duration::from_secs(10));
            tick.tick().await;
            loop {
                tick.tick().await;
                let Some(health) = weak.upgrade() else {
                    break;
                };
                let mut h = health.lock().unwrap();
                h.report();
            }
        });
        if let Some(stderr) = stderr {
            let weak = Arc::downgrade(&health);
            tokio::spawn(async move {
                let mut reader = BufReader::new(stderr);
                // Fixed buffer: an unexpectedly long stderr line cannot grow memory.
                let mut buffer = [0u8; 512];
                while let Ok(n) = reader.read(&mut buffer).await {
                    if n == 0 {
                        break;
                    }
                    let message = String::from_utf8_lossy(&buffer[..n]);
                    if let Some(health) = weak.upgrade() {
                        let mut h = health.lock().unwrap();
                        h.alsa_errors += 1;
                        if message.to_lowercase().contains("overrun") {
                            h.xruns += 1;
                        }
                        emit(
                            "alsa_error",
                            json!({"capture_id": h.capture_id, "message": message}),
                        );
                    }
                }
            });
        }
        // Publish the child before the reader starts. If arecord exits
        // immediately, the reader can still reap it instead of leaving a
        // stale child behind while the recorder is marked idle.
        self.arecord_thread.lock().await.replace(arecord_thread);
        let read_thread = tokio::spawn(async move {
            let _health_guard = CaptureGuard(health.clone());
            let bytes_per_sample = (capture_config.bits_per_sample.max(8) / 8) as usize;
            let bytes_per_frame = bytes_per_sample * capture_config.channels.max(1) as usize;
            let target_frames = capture_config.buffer_size.max(1) as usize;
            let read_frames = capture_config.period_size.max(1) as usize;
            let target_size = target_frames * bytes_per_frame;
            let read_size = read_frames * bytes_per_frame;

            let mut accumulated_data = Vec::with_capacity(target_size * 2);
            let mut buffer = vec![0u8; read_size];
            let mut consecutive_timeouts = 0usize;

            loop {
                match timeout(RECORD_READ_TIMEOUT, stdout.read(&mut buffer)).await {
                    Ok(Ok(size)) if size > 0 => {
                        {
                            let mut h = health.lock().unwrap();
                            let now = Instant::now();
                            let gap = now.duration_since(h.last_read).as_secs_f64() * 1000.0;
                            h.max_read_gap_ms = h.max_read_gap_ms.max(gap);
                            h.last_read = now;
                            h.captured_samples += (size / bytes_per_frame) as u64;
                        }
                        consecutive_timeouts = 0;
                        accumulated_data.extend_from_slice(&buffer[..size]);
                        while accumulated_data.len() >= target_size {
                            let data_to_send =
                                accumulated_data.drain(..target_size).collect::<Vec<u8>>();
                            let data_to_send = transform_stream_chunk(
                                data_to_send,
                                &requested_config,
                                &capture_config,
                            );
                            if !data_to_send.is_empty() {
                                let samples = data_to_send.len()
                                    / ((requested_config.bits_per_sample.max(8) / 8) as usize
                                        * requested_config.channels.max(1) as usize);
                                let meta = {
                                    let mut h = health.lock().unwrap();
                                    h.seq += 1;
                                    let meta = json!({"capture_id": h.capture_id, "seq": h.seq,
                                        "sample_start": h.attempted_samples, "samples": samples,
                                        "sample_rate": requested_config.sample_rate, "ts_ms": unix_ms()});
                                    h.attempted_samples += samples as u64;
                                    h.send_started = Some(Instant::now());
                                    if requested_config.bits_per_sample == 16 {
                                        h.levels(&data_to_send);
                                    }
                                    meta
                                };
                                let result = on_stream(data_to_send, meta).await;
                                let mut h = health.lock().unwrap();
                                if let Some(start) = h.send_started.take() {
                                    h.max_send_ms =
                                        h.max_send_ms.max(start.elapsed().as_secs_f64() * 1000.0);
                                }
                                if let Err(error) = result {
                                    h.send_errors += 1;
                                    emit(
                                        "send_error",
                                        json!({"capture_id": h.capture_id, "seq": h.seq, "error": error.to_string()}),
                                    );
                                } else {
                                    h.sent_samples += samples as u64;
                                    h.sent_packets += 1;
                                }
                            }
                        }
                    }
                    Ok(Ok(_)) => {
                        emit("capture_eof", json!({"capture_id": capture_id}));
                        eprintln!("⚠️ 录音进程已结束，等待服务端自动重启");
                        break;
                    }
                    Ok(Err(error)) => {
                        emit(
                            "capture_read_error",
                            json!({"capture_id": capture_id, "error": error.to_string()}),
                        );
                        eprintln!("⚠️ 读取录音数据失败: {error}，等待服务端自动重启");
                        break;
                    }
                    Err(_) => {
                        consecutive_timeouts += 1;
                        health.lock().unwrap().read_timeouts += 1;
                        emit(
                            "capture_read_timeout",
                            json!({"capture_id": capture_id, "consecutive": consecutive_timeouts}),
                        );
                        if recording_stalled(consecutive_timeouts) {
                            eprintln!(
                                "⚠️ 录音连续 {}ms 无数据，等待服务端自动重启",
                                RECORD_READ_TIMEOUT.as_millis()
                                    * MAX_CONSECUTIVE_READ_TIMEOUTS as u128
                            );
                            break;
                        }
                    }
                }
            }

            // Do not call stop_recording() from the reader task: it would abort
            // its own JoinHandle. Release the child first, then mark the
            // recorder idle so the server watchdog can start a fresh arecord.
            let recorder = AudioRecorder::instance();
            if let Some(mut arecord_thread) = recorder.arecord_thread.lock().await.take() {
                let _ = timeout(Duration::from_millis(100), arecord_thread.kill()).await;
            }
            *recorder.state.lock().await = State::Idle;
        });

        self.read_thread.lock().await.replace(read_thread);

        *state = State::Recording;
        Ok(())
    }
}

struct CaptureHealth {
    capture_id: String,
    rate: u32,
    captured_samples: u64,
    attempted_samples: u64,
    sent_samples: u64,
    sent_packets: u64,
    seq: u64,
    last_read: Instant,
    last_report: Instant,
    previous_captured: u64,
    previous_sent: u64,
    max_read_gap_ms: f64,
    max_send_ms: f64,
    send_started: Option<Instant>,
    send_errors: u64,
    read_timeouts: u64,
    alsa_errors: u64,
    xruns: u64,
    level_samples: u64,
    square_sum: f64,
    peak: f64,
    zeros: u64,
    clipped: u64,
}
impl CaptureHealth {
    fn new(config: &AudioConfig) -> Self {
        Self {
            capture_id: uuid::Uuid::new_v4().to_string(),
            rate: config.sample_rate,
            captured_samples: 0,
            attempted_samples: 0,
            sent_samples: 0,
            sent_packets: 0,
            seq: 0,
            last_read: Instant::now(),
            last_report: Instant::now(),
            previous_captured: 0,
            previous_sent: 0,
            max_read_gap_ms: 0.0,
            max_send_ms: 0.0,
            send_started: None,
            send_errors: 0,
            read_timeouts: 0,
            alsa_errors: 0,
            xruns: 0,
            level_samples: 0,
            square_sum: 0.0,
            peak: 0.0,
            zeros: 0,
            clipped: 0,
        }
    }
    fn levels(&mut self, data: &[u8]) {
        for bytes in data.chunks_exact(2) {
            let sample = i16::from_le_bytes([bytes[0], bytes[1]]);
            let value = sample as f64 / 32768.0;
            self.square_sum += value * value;
            self.peak = self.peak.max(value.abs());
            self.zeros += u64::from(sample == 0);
            self.clipped += u64::from(sample == i16::MIN || sample == i16::MAX);
            self.level_samples += 1;
        }
    }
    fn report(&mut self) {
        let elapsed = self.last_report.elapsed().as_secs_f64().max(0.001);
        let n = self.level_samples.max(1) as f64;
        emit(
            "summary",
            json!({"capture_id": self.capture_id, "window_s": elapsed,
            "sample_rate": self.rate, "seq": self.seq, "captured_samples_total": self.captured_samples,
            "sent_samples_total": self.sent_samples, "sent_packets_total": self.sent_packets,
            "capture_rate_hz": (self.captured_samples-self.previous_captured) as f64/elapsed,
            "send_rate_hz": (self.sent_samples-self.previous_sent) as f64/elapsed,
            "input_age_ms": self.last_read.elapsed().as_secs_f64()*1000.0,
            "max_read_gap_ms": self.max_read_gap_ms, "max_send_ms": self.max_send_ms,
            "send_pending_ms": self.send_started.map(|t| t.elapsed().as_secs_f64()*1000.0).unwrap_or(0.0),
            "read_timeouts_total": self.read_timeouts, "send_errors_total": self.send_errors,
            "alsa_errors_total": self.alsa_errors, "xruns_total": self.xruns,
            "rms": (self.square_sum/n).sqrt(), "peak": self.peak,
            "zero_ratio": self.zeros as f64/n, "clip_ratio": self.clipped as f64/n,
            "level_samples": self.level_samples}),
        );
        self.last_report = Instant::now();
        self.previous_captured = self.captured_samples;
        self.previous_sent = self.sent_samples;
        self.max_read_gap_ms = 0.0;
        self.max_send_ms = 0.0;
        self.level_samples = 0;
        self.square_sum = 0.0;
        self.peak = 0.0;
        self.zeros = 0;
        self.clipped = 0;
    }
}
struct CaptureGuard(Arc<StdMutex<CaptureHealth>>);
impl Drop for CaptureGuard {
    fn drop(&mut self) {
        let mut h = self.0.lock().unwrap();
        h.report();
        emit(
            "capture_stop",
            json!({"capture_id": h.capture_id, "seq": h.seq}),
        );
    }
}

fn recording_stalled(consecutive_timeouts: usize) -> bool {
    consecutive_timeouts >= MAX_CONSECUTIVE_READ_TIMEOUTS
}

fn capture_config_for_recording(requested: &AudioConfig) -> AudioConfig {
    let mut capture = requested.clone();
    if requested.bits_per_sample == 16 {
        capture.bits_per_sample = A113_CAPTURE_BITS_PER_SAMPLE;
    }
    capture
}

fn transform_stream_chunk(
    chunk: Vec<u8>,
    requested: &AudioConfig,
    capture: &AudioConfig,
) -> Vec<u8> {
    if requested.bits_per_sample != 16 || capture.bits_per_sample != A113_CAPTURE_BITS_PER_SAMPLE {
        return chunk;
    }
    convert_a113_s32_to_s16(&chunk)
}

fn convert_a113_s32_to_s16(chunk: &[u8]) -> Vec<u8> {
    if chunk.len() % 4 != 0 {
        return Vec::new();
    }

    let frame_count = chunk.len() / 4;
    let mut out = vec![0u8; frame_count * 2];

    for frame in 0..frame_count {
        let base = frame * 4;
        let sample = i32::from_le_bytes([
            chunk[base],
            chunk[base + 1],
            chunk[base + 2],
            chunk[base + 3],
        ]);
        // A113 PDM data lives in lower 24 bits of S32_LE: shift by 8 (not 16).
        let mapped = (sample >> 8).clamp(i16::MIN as i32, i16::MAX as i32) as i16;
        let out_base = frame * 2;
        out[out_base..out_base + 2].copy_from_slice(&mapped.to_le_bytes());
    }

    out
}

fn spawn_arecord(config: &AudioConfig) -> Result<Child, AppError> {
    let child = Command::new("arecord")
        .args([
            "--quiet",
            "-t",
            "raw",
            "-D",
            &config.pcm,
            "-f",
            &format!("S{}_LE", config.bits_per_sample),
            "-r",
            &config.sample_rate.to_string(),
            "-c",
            &config.channels.to_string(),
            "--buffer-size",
            &config.buffer_size.to_string(),
            "--period-size",
            &config.period_size.to_string(),
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    Ok(child)
}

#[cfg(test)]
mod tests {
    use super::{convert_a113_s32_to_s16, recording_stalled, CaptureHealth, AUDIO_CONFIG};

    #[test]
    fn health_counts_s16_levels_without_changing_audio() {
        let mut h = CaptureHealth::new(&AUDIO_CONFIG);
        let data = [0i16, i16::MIN, i16::MAX, 0]
            .iter()
            .flat_map(|sample| sample.to_le_bytes())
            .collect::<Vec<_>>();
        h.levels(&data);
        assert_eq!(h.level_samples, 4);
        assert_eq!(h.zeros, 2);
        assert_eq!(h.clipped, 2);
        assert_eq!(h.peak, 1.0);
        assert!(h.square_sum > 1.99);
    }

    #[test]
    fn tolerates_transient_recording_gaps() {
        assert!(!recording_stalled(1));
        assert!(!recording_stalled(9));
        assert!(recording_stalled(10));
    }

    #[test]
    fn converts_a113_s32_samples_to_s16() {
        let samples = [0x007f_ff00i32, -0x0080_0000i32];
        let input = samples
            .iter()
            .flat_map(|sample| sample.to_le_bytes())
            .collect::<Vec<_>>();

        let output = convert_a113_s32_to_s16(&input);

        assert_eq!(output, [0xff, 0x7f, 0x00, 0x80]);
    }
}
