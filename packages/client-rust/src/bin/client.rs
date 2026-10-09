use open_xiaoai::services::audio::config::AudioConfig;
use open_xiaoai::services::audio::echo_ref::EchoRefConfig;
use open_xiaoai::services::monitor::kws::KwsMonitor;
use serde_json::json;
use std::time::{Duration, Instant};
use tokio::net::{lookup_host, TcpSocket};
use tokio::time::{sleep, timeout};
use tokio_tungstenite::{client_async, MaybeTlsStream};

use open_xiaoai::base::AppError;
use open_xiaoai::base::VERSION;
use open_xiaoai::services::audio::play::AudioPlayer;
use open_xiaoai::services::audio::record::AudioRecorder;
use open_xiaoai::services::connect::data::{Event, Request, Response, Stream};
use open_xiaoai::services::connect::handler::MessageHandler;
use open_xiaoai::services::connect::message::{MessageManager, WsStream};
use open_xiaoai::services::connect::rpc::RPC;
use open_xiaoai::services::monitor::instruction::InstructionMonitor;
use open_xiaoai::services::monitor::playing::PlayingMonitor;
use open_xiaoai::utils::audio_health::emit;

/// Each step of connecting has its own deadline, so a lossy network cannot
/// leave the client waiting on a handshake that will never finish.
const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);
/// Seconds from the start of the 1st, 2nd, ... failed attempt to the next one;
/// then one every 5 s. A timed-out attempt has already waited, so the next
/// starts at once. An attempt costs a few SYNs, and a short cap means a quick
/// return once the network is back.
const RETRY_DELAYS: [u64; 3] = [1, 2, 5];
/// Kernel send buffer (Linux doubles it): about 1 s of audio. Audio that falls
/// further behind is dropped in the app queue rather than piling up here.
const SEND_BUFFER_BYTES: u32 = 16 * 1024;

struct AppClient {
    kws_monitor: KwsMonitor,
    instruction_monitor: InstructionMonitor,
    playing_monitor: PlayingMonitor,
}

impl AppClient {
    pub fn new() -> Self {
        Self {
            kws_monitor: KwsMonitor::new(),
            instruction_monitor: InstructionMonitor::new(),
            playing_monitor: PlayingMonitor::new(),
        }
    }

    pub async fn connect(&self, url: &str) -> Result<WsStream, AppError> {
        let host = url.split("://").last().unwrap_or(url);
        let host = host.split('/').next().unwrap_or(host);
        let host = if host.contains(':') { host.to_string() } else { format!("{host}:80") };
        let addr = timeout(CONNECT_TIMEOUT, lookup_host(host))
            .await
            .map_err(|_| "resolve timeout")??
            .next()
            .ok_or("no address for server")?;
        let socket = if addr.is_ipv4() { TcpSocket::new_v4()? } else { TcpSocket::new_v6()? };
        socket.set_send_buffer_size(SEND_BUFFER_BYTES)?;
        let tcp = timeout(CONNECT_TIMEOUT, socket.connect(addr))
            .await
            .map_err(|_| "connect timeout")??;
        tcp.set_nodelay(true)?;
        let (ws_stream, _) = timeout(CONNECT_TIMEOUT, client_async(url, MaybeTlsStream::Plain(tcp)))
            .await
            .map_err(|_| "handshake timeout")??;
        Ok(WsStream::Client(ws_stream))
    }

    pub async fn run(&mut self) {
        let url = std::env::args().nth(1).expect("❌ 请输入服务器地址");
        println!("✅ 已启动");
        // Never gives up: the speaker keeps retrying until the server is back.
        let mut failures = 0usize;
        loop {
            let started = Instant::now();
            let ws_stream = match self.connect(&url).await {
                Ok(stream) => stream,
                Err(error) => {
                    let delay = Duration::from_secs(RETRY_DELAYS[failures.min(RETRY_DELAYS.len() - 1)])
                        .saturating_sub(started.elapsed());
                    failures += 1;
                    emit(
                        "connect_error",
                        json!({"error": error.to_string(), "attempt": failures,
                        "retry_in_ms": delay.as_millis() as u64}),
                    );
                    sleep(delay).await;
                    continue;
                }
            };
            failures = 0;
            emit("connected", json!({}));
            println!("✅ 已连接: {:?}", url);
            self.init(ws_stream).await;
            let reason = match MessageManager::instance().process_messages().await {
                Ok(()) => "closed by server".to_string(),
                Err(e) => e.to_string(),
            };
            self.dispose().await;
            emit("disconnected", json!({"reason": reason}));
            eprintln!("❌ 已断开连接: {}", reason);
            sleep(Duration::from_secs(1)).await;
        }
    }

    async fn init(&mut self, ws_stream: WsStream) {
        MessageManager::instance().init(ws_stream).await;
        MessageHandler::<Event>::instance()
            .set_handler(on_event)
            .await;
        MessageHandler::<Stream>::instance()
            .set_handler(on_stream)
            .await;

        let rpc = RPC::instance();
        rpc.add_command("get_version", get_version).await;
        rpc.add_command("run_shell", run_shell).await;
        rpc.add_command("start_play", start_play).await;
        rpc.add_command("stop_play", stop_play).await;
        rpc.add_command("start_recording", start_recording).await;
        rpc.add_command("stop_recording", stop_recording).await;

        self.instruction_monitor
            .start(|event| async move {
                MessageManager::instance()
                    .send_event("instruction", Some(json!(event)))
                    .await
            })
            .await;

        self.playing_monitor
            .start(|event| async move {
                MessageManager::instance()
                    .send_event("playing", Some(json!(event)))
                    .await
            })
            .await;

        self.kws_monitor
            .start(|event| async move {
                MessageManager::instance()
                    .send_event("kws", Some(json!(event)))
                    .await
            })
            .await;
    }

    async fn dispose(&mut self) {
        MessageManager::instance().dispose().await;
        let _ = AudioPlayer::instance().stop().await;
        let _ = AudioRecorder::instance().stop_recording().await;
        self.instruction_monitor.stop().await;
        self.playing_monitor.stop().await;
        self.kws_monitor.stop().await;
    }
}

async fn get_version(_: Request) -> Result<Response, AppError> {
    let data = json!(VERSION.to_string());
    Ok(Response::from_data(data))
}

async fn start_play(request: Request) -> Result<Response, AppError> {
    let config = request
        .payload
        .and_then(|payload| serde_json::from_value::<AudioConfig>(payload).ok());
    AudioPlayer::instance().start(config).await?;
    Ok(Response::success())
}

async fn stop_play(_: Request) -> Result<Response, AppError> {
    AudioPlayer::instance().stop().await?;
    Ok(Response::success())
}

async fn start_recording(request: Request) -> Result<Response, AppError> {
    // `echo_ref` rides next to the AudioConfig fields, so older servers and
    // clients that do not know it keep working with plain mono capture.
    let echo_ref = request
        .payload
        .as_ref()
        .and_then(|payload| payload.get("echo_ref").cloned())
        .and_then(|value| serde_json::from_value::<EchoRefConfig>(value).ok());
    let config = request
        .payload
        .and_then(|payload| serde_json::from_value::<AudioConfig>(payload).ok());
    AudioRecorder::instance()
        .start_recording_with(
            |bytes, meta| async {
                MessageManager::instance()
                    .send_stream_realtime("record", bytes, Some(meta))
                    .await
            },
            config,
            echo_ref,
        )
        .await?;
    Ok(Response::success())
}

async fn stop_recording(_: Request) -> Result<Response, AppError> {
    AudioRecorder::instance().stop_recording().await?;
    Ok(Response::success())
}

async fn run_shell(request: Request) -> Result<Response, AppError> {
    let script = match request.payload {
        Some(payload) => serde_json::from_value::<String>(payload)?,
        _ => return Err("empty command".into()),
    };
    let res = open_xiaoai::utils::shell::run_shell(script.as_str()).await?;
    Ok(Response::from_data(json!(res)))
}

async fn on_event(event: Event) -> Result<(), AppError> {
    println!("🔥 收到事件: {:?}", event);
    Ok(())
}

async fn on_stream(stream: Stream) -> Result<(), AppError> {
    let Stream { tag, bytes, .. } = stream;
    if tag.as_str() == "play" {
        // 播放接收到的音频流
        let _ = AudioPlayer::instance().play(bytes).await;
    }
    Ok(())
}

#[tokio::main]
async fn main() {
    AppClient::new().run().await;
}
