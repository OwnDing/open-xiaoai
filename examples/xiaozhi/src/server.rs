use crate::python::PythonManager;
use open_xiaoai::base::{AppError, VERSION};
use open_xiaoai::services::audio::config::AudioConfig;
use open_xiaoai::services::connect::data::{Event, Request, Response, Stream};
use open_xiaoai::services::connect::handler::MessageHandler;
use open_xiaoai::services::connect::message::{MessageManager, WsStream};
use open_xiaoai::services::connect::rpc::RPC;
use open_xiaoai::services::speaker::SpeakerManager;
use open_xiaoai::utils::task::TaskManager;
use pyo3::prelude::*;
use pyo3::types::PyString;
use pyo3::types::{PyBytes, PyTuple};
use pyo3::Python;
use serde_json::json;
use std::sync::{LazyLock, Mutex as StdMutex};
use std::time::Instant;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio::time::{sleep, timeout, Duration};
use tokio_tungstenite::accept_async;

pub struct AppServer;

/// A WebSocket handshake not finished in this time is abandoned.
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(10);
/// Say "已连接" at startup and after the speaker was away this long, not after
/// every quick reconnect on a flaky Wi-Fi.
const ANNOUNCE_AFTER: Duration = Duration::from_secs(60);

/// The speaker connection being served; there is one speaker per bridge.
static ACTIVE: LazyLock<Mutex<Option<JoinHandle<()>>>> = LazyLock::new(|| Mutex::new(None));
static LAST_DISCONNECT: LazyLock<StdMutex<Option<Instant>>> = LazyLock::new(|| StdMutex::new(None));
/// Sent as `echo_ref` with every recording request when set (see
/// `set_echo_ref`): the speaker then also sends its playback loopback.
static ECHO_REF: LazyLock<StdMutex<Option<serde_json::Value>>> = LazyLock::new(|| StdMutex::new(None));

pub fn set_echo_ref(config: Option<serde_json::Value>) {
    *ECHO_REF.lock().unwrap() = config;
}

async fn audio_watchdog() {
    let mut recording_config = json!(AudioConfig {
        pcm: "noop".into(),
        channels: 1,
        bits_per_sample: 16,
        sample_rate: 16000,
        period_size: 1440 / 4,
        buffer_size: 1440,
    });
    if let Some(echo_ref) = ECHO_REF.lock().unwrap().clone() {
        recording_config["echo_ref"] = echo_ref;
    }
    // On a lossy link the reply can take seconds; the microphone must not wait
    // for the player (which native_xiaomi output does not even use).
    let start_play = tokio::spawn(async {
        let _ = RPC::instance()
            .call_remote(
                "start_play",
                Some(json!(AudioConfig {
                    pcm: "noop".into(),
                    channels: 1,
                    bits_per_sample: 16,
                    sample_rate: 24000,
                    // Keep enough audio queued to absorb Wi-Fi and scheduler jitter.
                    period_size: 960,  // 40 ms at 24 kHz
                    buffer_size: 4800, // 200 ms at 24 kHz
                })),
                None,
            )
            .await;
    });
    TaskManager::instance().add("audio_watchdog", start_play).await;

    loop {
        {
            let started = Instant::now();
            let result = RPC::instance()
                .call_remote(
                    "start_recording",
                    Some(recording_config.clone()),
                    Some(3_000),
                )
                .await;
            health_event(
                "recording_rpc",
                json!({"ok": result.is_ok(),
            "duration_ms": started.elapsed().as_secs_f64()*1000.0,
            "error": result.as_ref().err().map(|e| e.to_string())}),
            );
            if let Err(error) = result {
                crate::pylog!("⚠️ 录音健康检查失败: {}", error);
            }
        }
        sleep(Duration::from_secs(5)).await;
    }
}

impl AppServer {
    pub async fn connect(stream: TcpStream) -> Result<WsStream, AppError> {
        let ws_stream = accept_async(stream).await?;
        Ok(WsStream::Server(ws_stream))
    }

    pub async fn run() {
        let addr = "0.0.0.0:4399";
        let listener = TcpListener::bind(&addr)
            .await
            .expect(format!("❌ 绑定地址失败: {}", &addr).as_str());
        crate::pylog!("✅ 已启动: {:?}", addr);
        while let Ok((stream, addr)) = listener.accept().await {
            tokio::spawn(AppServer::take_over(stream, addr));
        }
    }

    /// Serves one connection at a time. A new connection from the speaker
    /// means it gave up on the old one (or rebooted), so the old one is closed
    /// at once instead of making the speaker wait until it times out here.
    async fn take_over(stream: TcpStream, addr: std::net::SocketAddr) {
        let ws_stream = match timeout(HANDSHAKE_TIMEOUT, AppServer::connect(stream)).await {
            Ok(Ok(ws_stream)) => ws_stream,
            _ => {
                crate::pylog!("❌ 连接异常: {}", addr);
                return;
            }
        };
        let mut active = ACTIVE.lock().await;
        if let Some(old) = active.take() {
            if !old.is_finished() {
                MessageManager::instance().cancel("replaced by a new connection");
                let _ = old.await;
            }
        }
        *active = Some(tokio::spawn(AppServer::handle_connection(ws_stream, addr)));
    }

    async fn handle_connection(ws_stream: WsStream, addr: std::net::SocketAddr) {
        health_event("connected", json!({"peer": addr.to_string()}));
        crate::pylog!("✅ 已连接: {:?}", addr);
        AppServer::init(ws_stream).await;
        let reason = match MessageManager::instance().process_messages().await {
            Ok(()) => "closed by speaker".to_string(),
            Err(e) => e.to_string(),
        };
        AppServer::dispose().await;
        *LAST_DISCONNECT.lock().unwrap() = Some(Instant::now());
        health_event("disconnected", json!({"reason": reason}));
        crate::pylog!("❌ 已断开连接: {}", reason);
    }

    async fn init(ws_stream: WsStream) {
        MessageManager::instance().init(ws_stream).await;
        MessageHandler::<Event>::instance()
            .set_handler(on_event)
            .await;
        MessageHandler::<Stream>::instance()
            .set_handler(on_stream)
            .await;

        let rpc = RPC::instance();
        rpc.add_command("get_version", get_version).await;

        let audio_watchdog = tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            audio_watchdog().await;
        });
        TaskManager::instance()
            .add("audio_watchdog", audio_watchdog)
            .await;

        let announce = LAST_DISCONNECT
            .lock()
            .unwrap()
            .map_or(true, |at| at.elapsed() >= ANNOUNCE_AFTER);
        if announce {
            // The welcome prompt must never delay microphone startup.
            let welcome = tokio::spawn(async move {
                let _ = SpeakerManager::play_text("已连接").await;
            });
            TaskManager::instance().add("welcome", welcome).await;
        }
    }

    async fn dispose() {
        MessageManager::instance().dispose().await;
        TaskManager::instance().dispose("audio_watchdog").await;
        TaskManager::instance().dispose("welcome").await;
    }
}

async fn get_version(_: Request) -> Result<Response, AppError> {
    let data = json!(VERSION.to_string());
    Ok(Response::from_data(data))
}

async fn on_stream(stream: Stream) -> Result<(), AppError> {
    let Stream {
        tag,
        bytes,
        data: metadata,
        ..
    } = stream;
    match tag.as_str() {
        "record" => {
            let metadata = serde_json::to_string(&metadata)?;
            let data = Python::with_gil(|py| -> PyResult<PyObject> {
                Ok(PyTuple::new(
                    py,
                    [
                        PyBytes::new(py, &bytes).into_any(),
                        PyString::new(py, &metadata).into_any(),
                    ],
                )?
                .into())
            })?;
            if let Err(error) = PythonManager::instance().call_fn("on_input_packet", Some(data)) {
                health_event("input_callback_error", json!({"error": error.to_string()}));
                return Err(error.into());
            }
        }
        _ => {}
    }
    Ok(())
}

async fn on_event(event: Event) -> Result<(), AppError> {
    let event_json = serde_json::to_string(&event)?;
    let data = Python::with_gil(|py| PyString::new(py, &event_json).into());
    PythonManager::instance().call_fn("on_event", Some(data))?;
    Ok(())
}

fn health_event(event: &str, fields: serde_json::Value) {
    let data = json!({"event": event, "fields": fields}).to_string();
    let arg = Python::with_gil(|py| PyString::new(py, &data).into());
    let _ = PythonManager::instance().call_fn("on_health_event", Some(arg));
}
