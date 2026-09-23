use crate::python::PythonManager;
use open_xiaoai::base::{AppError, VERSION};
use open_xiaoai::services::audio::config::AudioConfig;
use open_xiaoai::services::connect::data::{Event, Request, Response, Stream};
use open_xiaoai::services::connect::handler::MessageHandler;
use open_xiaoai::services::connect::message::{MessageManager, WsStream};
use open_xiaoai::services::connect::rpc::RPC;
use open_xiaoai::services::speaker::SpeakerManager;
use open_xiaoai::utils::task::TaskManager;
use pyo3::types::PyBytes;
use pyo3::types::PyString;
use pyo3::Python;
use serde_json::json;
use tokio::net::{TcpListener, TcpStream};
use tokio::time::{sleep, Duration};
use tokio_tungstenite::accept_async;

pub struct AppServer;

async fn audio_watchdog() {
    let recording_config = json!(AudioConfig {
        pcm: "noop".into(),
        channels: 1,
        bits_per_sample: 16,
        sample_rate: 16000,
        period_size: 1440 / 4,
        buffer_size: 1440,
    });
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

    loop {
        if let Err(error) = RPC::instance()
            .call_remote(
                "start_recording",
                Some(recording_config.clone()),
                Some(3_000),
            )
            .await
        {
            crate::pylog!("⚠️ 录音健康检查失败: {}", error);
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
            // 同一时刻只处理一个连接
            AppServer::handle_connection(stream, addr).await;
        }
    }

    async fn handle_connection(stream: TcpStream, addr: std::net::SocketAddr) {
        let Ok(ws_stream) = AppServer::connect(stream).await else {
            crate::pylog!("❌ 连接异常: {}", addr);
            return;
        };
        crate::pylog!("✅ 已连接: {:?}", addr);
        AppServer::init(ws_stream).await;
        if let Err(e) = MessageManager::instance().process_messages().await {
            crate::pylog!("❌ 消息处理异常: {}", e);
        }
        AppServer::dispose().await;
        crate::pylog!("❌ 已断开连接");
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

        // The welcome prompt must never delay microphone startup.
        let welcome = tokio::spawn(async move {
            let _ = SpeakerManager::play_text("已连接").await;
        });
        TaskManager::instance().add("welcome", welcome).await;
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
    let Stream { tag, bytes, .. } = stream;
    match tag.as_str() {
        "record" => {
            let data = Python::with_gil(|py| PyBytes::new(py, &bytes).into());
            PythonManager::instance().call_fn("on_input_data", Some(data))?;
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
