//! MessageManager over a real loopback WebSocket: frames, pings and the two
//! ways a dead link is noticed. One test because MessageManager is a singleton.

use futures::StreamExt;
use open_xiaoai::services::connect::data::Stream;
use open_xiaoai::services::connect::message::{LinkTimeouts, MessageManager, WsStream};
use serde_json::json;
use std::time::{Duration, Instant};
use tokio::net::{TcpListener, TcpSocket, TcpStream};
use tokio::time::{sleep, timeout};
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{accept_async, client_async, MaybeTlsStream, WebSocketStream};

const MS: fn(u64) -> Duration = Duration::from_millis;

async fn pair(send_buffer: Option<u32>) -> (WebSocketStream<TcpStream>, WsStream) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let accept = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        accept_async(stream).await.unwrap()
    });
    let socket = TcpSocket::new_v4().unwrap();
    if let Some(bytes) = send_buffer {
        socket.set_send_buffer_size(bytes).unwrap();
    }
    let tcp = socket.connect(addr).await.unwrap();
    let (ours, _) = client_async(format!("ws://{addr}/"), MaybeTlsStream::Plain(tcp))
        .await
        .unwrap();
    (accept.await.unwrap(), WsStream::Client(ours))
}

fn spawn_reader() -> tokio::task::JoinHandle<Result<(), String>> {
    tokio::spawn(async {
        MessageManager::instance()
            .process_messages()
            .await
            .map_err(|e| e.to_string())
    })
}

#[tokio::test(flavor = "multi_thread")]
async fn link_lifecycle() {
    let manager = MessageManager::instance();
    assert!(manager.send(Message::text("x")).await.is_err(), "no link yet");

    // 1. Audio arrives as a binary frame, pings arrive, and a peer that keeps
    //    reading (so it answers pings) keeps the link up past the idle timeout.
    manager.set_timeouts(LinkTimeouts {
        ping_interval: MS(100),
        idle_timeout: MS(600),
        send_timeout: MS(300),
    });
    let (mut peer, ours) = pair(None).await;
    manager.init(ours).await;
    let reader = spawn_reader();
    manager
        .send_stream_realtime("record", vec![1, 2, 3, 4], Some(json!({"seq": 1})))
        .await
        .unwrap();
    let (mut pinged, mut audio) = (false, None);
    let deadline = Instant::now() + Duration::from_secs(2);
    while (!pinged || audio.is_none()) && Instant::now() < deadline {
        match timeout(MS(500), peer.next()).await {
            Ok(Some(Ok(Message::Ping(_)))) => pinged = true,
            Ok(Some(Ok(Message::Binary(frame)))) => {
                assert_eq!(&frame[..4], b"OXS1");
                audio = Some(Stream::decode(&frame).unwrap());
            }
            _ => {}
        }
    }
    assert!(pinged, "no ping within 2 s");
    let audio = audio.expect("no audio frame");
    assert_eq!((audio.tag.as_str(), audio.bytes), ("record", vec![1, 2, 3, 4]));
    assert_eq!(audio.data, Some(json!({"seq": 1})));
    let keep_reading = tokio::spawn(async move { while let Some(Ok(_)) = peer.next().await {} });
    sleep(MS(1200)).await;
    assert!(!reader.is_finished(), "a healthy link was dropped");
    manager.cancel("replaced");
    assert_eq!(reader.await.unwrap().unwrap_err(), "replaced");
    manager.dispose().await;
    keep_reading.abort();

    // 2. A peer that goes silent is noticed after the idle timeout.
    let (silent_peer, ours) = pair(None).await;
    manager.init(ours).await;
    let started = Instant::now();
    let error = manager.process_messages().await.unwrap_err().to_string();
    assert!(error.contains("nothing received"), "{error}");
    assert!(started.elapsed() < MS(1500), "{:?}", started.elapsed());
    manager.dispose().await;
    drop(silent_peer);

    // 3. A peer that stops reading makes a write hang; that is noticed after
    //    the send timeout, and live audio queued meanwhile drops oldest first.
    manager.set_timeouts(LinkTimeouts {
        ping_interval: Duration::from_secs(10),
        idle_timeout: Duration::from_secs(10),
        send_timeout: MS(300),
    });
    let (stuck_peer, ours) = pair(Some(4096)).await;
    manager.init(ours).await;
    let reader = spawn_reader();
    for _ in 0..64 {
        manager.send_stream("play", vec![0; 256 * 1024], None).await.unwrap();
    }
    let mut dropped = 0;
    for seq in 0..40 {
        dropped += manager
            .send_stream_realtime("record", vec![0; 2880], Some(json!({"seq": seq})))
            .await
            .unwrap_or(0);
    }
    assert_eq!(dropped, 40 - 12, "the queue keeps the newest ~1 s of audio");
    let error = timeout(Duration::from_secs(3), reader).await.unwrap().unwrap().unwrap_err();
    assert!(error.contains("send stalled"), "{error}");
    assert!(manager.send(Message::text("x")).await.is_err(), "a failed link refuses sends");
    manager.dispose().await;
    drop(stuck_peer);
}
