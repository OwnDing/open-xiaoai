use futures::stream::{SplitSink, SplitStream};
use futures::{SinkExt, StreamExt};
use serde_json::Value;
use std::collections::VecDeque;
use std::future::Future;
use std::sync::{Arc, LazyLock, Mutex as StdMutex};
use std::time::Duration;
use tokio::net::TcpStream;
use tokio::sync::{Mutex, Notify, Semaphore};
use tokio::time::{sleep, timeout};
use tokio_tungstenite::tungstenite::Error as WsError;
use tokio_tungstenite::MaybeTlsStream;
use tokio_tungstenite::{tungstenite::Message, WebSocketStream};

use super::rpc::RPC;
use crate::base::AppError;
use crate::utils::task::TaskManager;

use super::data::{AppMessage, Event, Request, Response, Stream};
use super::handler::MessageHandler;

pub enum WsStream {
    Server(WebSocketStream<TcpStream>),
    Client(WebSocketStream<MaybeTlsStream<TcpStream>>),
}

pub enum WsReader {
    Server(SplitStream<WebSocketStream<TcpStream>>),
    Client(SplitStream<WebSocketStream<MaybeTlsStream<TcpStream>>>),
}

pub enum WsWriter {
    Server(SplitSink<WebSocketStream<TcpStream>, Message>),
    Client(SplitSink<WebSocketStream<MaybeTlsStream<TcpStream>>, Message>),
}

impl WsReader {
    async fn next(&mut self) -> Option<Result<Message, WsError>> {
        match self {
            WsReader::Client(reader) => reader.next().await,
            WsReader::Server(reader) => reader.next().await,
        }
    }
}

impl WsWriter {
    async fn send(&mut self, msg: Message) -> Result<(), WsError> {
        match self {
            WsWriter::Client(writer) => writer.send(msg).await,
            WsWriter::Server(writer) => writer.send(msg).await,
        }
    }
}

/// When to give up on a connection. A lossy Wi-Fi link does not break a TCP
/// connection: the kernel keeps retransmitting with doubling waits for 15+
/// minutes, so without these limits the link went silent for minutes at a time
/// instead of reconnecting.
#[derive(Clone, Copy, Debug)]
pub struct LinkTimeouts {
    /// Send a WebSocket ping this often; the peer answers with a pong.
    pub ping_interval: Duration,
    /// Nothing at all received for this long: the link is dead.
    pub idle_timeout: Duration,
    /// One frame could not be written for this long: the link is dead.
    pub send_timeout: Duration,
}

impl Default for LinkTimeouts {
    fn default() -> Self {
        Self {
            ping_interval: Duration::from_secs(5),
            idle_timeout: Duration::from_secs(15),
            send_timeout: Duration::from_secs(10),
        }
    }
}

/// Live audio queued beyond this many frames is dropped, oldest first: audio
/// that arrives late is worse than audio that is missing. 12 × 90 ms ≈ 1 s.
const REALTIME_QUEUE_FRAMES: usize = 12;
/// Control messages and lossless streams are never dropped; a queue this long
/// means the link has stopped moving and the send is refused.
const QUEUE_LIMIT: usize = 1024;
const LINK_TASKS: &str = "MessageManager.link";

/// Frames waiting for the writer. Control (requests, responses, events, pings)
/// goes first, then lossless streams, then live audio, so a backlog of audio
/// never holds up a reply.
#[derive(Default)]
struct Outbox {
    control: VecDeque<Message>,
    bulk: VecDeque<Message>,
    realtime: VecDeque<Message>,
}

impl Outbox {
    fn pop(&mut self) -> Option<Message> {
        self.control
            .pop_front()
            .or_else(|| self.bulk.pop_front())
            .or_else(|| self.realtime.pop_front())
    }

    fn push_bounded(queue: &mut VecDeque<Message>, msg: Message) -> Result<usize, String> {
        if queue.len() >= QUEUE_LIMIT {
            return Err("send queue full".into());
        }
        queue.push_back(msg);
        Ok(0)
    }

    /// Returns how many older frames were dropped to make room.
    fn push_realtime(&mut self, msg: Message) -> usize {
        self.realtime.push_back(msg);
        let mut dropped = 0;
        while self.realtime.len() > REALTIME_QUEUE_FRAMES {
            self.realtime.pop_front();
            dropped += 1;
        }
        dropped
    }
}

/// State of one connection, shared by the reader, the writer and the pinger.
struct Link {
    outbox: StdMutex<Outbox>,
    /// Wakes the writer when something is queued.
    wake: Notify,
    /// Wakes the reader when the connection has failed or was cancelled.
    stop: Notify,
    failure: StdMutex<Option<String>>,
}

impl Link {
    fn new() -> Self {
        Self {
            outbox: StdMutex::new(Outbox::default()),
            wake: Notify::new(),
            stop: Notify::new(),
            failure: StdMutex::new(None),
        }
    }

    fn push(&self, add: impl FnOnce(&mut Outbox) -> Result<usize, String>) -> Result<usize, String> {
        if let Some(reason) = self.failure() {
            return Err(reason);
        }
        let result = add(&mut self.outbox.lock().unwrap());
        self.wake.notify_one();
        result
    }

    fn fail(&self, reason: &str) {
        self.failure.lock().unwrap().get_or_insert_with(|| reason.to_string());
        self.stop.notify_one();
        self.wake.notify_one();
    }

    fn failure(&self) -> Option<String> {
        self.failure.lock().unwrap().clone()
    }
}

async fn write_loop(mut writer: WsWriter, link: Arc<Link>, send_timeout: Duration) {
    loop {
        let next = link.outbox.lock().unwrap().pop();
        let Some(msg) = next else {
            if link.failure().is_some() {
                return;
            }
            link.wake.notified().await;
            continue;
        };
        match timeout(send_timeout, writer.send(msg)).await {
            Ok(Ok(())) => {}
            Ok(Err(error)) => return link.fail(&format!("send failed: {error}")),
            Err(_) => {
                return link.fail(&format!("send stalled for {}s", send_timeout.as_secs()))
            }
        }
    }
}

async fn ping_loop(link: Arc<Link>, interval: Duration) {
    loop {
        sleep(interval).await;
        let ping = Message::Ping(Vec::new().into());
        if link
            .push(|outbox| Outbox::push_bounded(&mut outbox.control, ping))
            .is_err()
        {
            return;
        }
    }
}

pub struct MessageManager {
    semaphore: Arc<Semaphore>,
    reader: Arc<Mutex<Option<WsReader>>>,
    link: StdMutex<Option<Arc<Link>>>,
    timeouts: StdMutex<LinkTimeouts>,
}

static INSTANCE: LazyLock<MessageManager> = LazyLock::new(MessageManager::new);

impl MessageManager {
    fn new() -> Self {
        Self {
            reader: Arc::new(Mutex::new(None)),
            link: StdMutex::new(None),
            timeouts: StdMutex::new(LinkTimeouts::default()),
            semaphore: Arc::new(Semaphore::new(32)),
        }
    }

    pub fn instance() -> &'static Self {
        &INSTANCE
    }

    /// Applies to connections initialised afterwards.
    pub fn set_timeouts(&self, timeouts: LinkTimeouts) {
        *self.timeouts.lock().unwrap() = timeouts;
    }

    fn current_link(&self) -> Result<Arc<Link>, AppError> {
        self.link
            .lock()
            .unwrap()
            .clone()
            .ok_or_else(|| "WebSocket is not initialized".into())
    }

    pub async fn init(&self, ws_stream: WsStream) {
        let (writer, reader) = match ws_stream {
            WsStream::Client(stream) => {
                let (tx, rx) = stream.split();
                (WsWriter::Client(tx), WsReader::Client(rx))
            }
            WsStream::Server(stream) => {
                let (tx, rx) = stream.split();
                (WsWriter::Server(tx), WsReader::Server(rx))
            }
        };
        let timeouts = *self.timeouts.lock().unwrap();
        let link = Arc::new(Link::new());
        self.reader.lock().await.replace(reader);
        self.link.lock().unwrap().replace(link.clone());
        let writer = tokio::spawn(write_loop(writer, link.clone(), timeouts.send_timeout));
        let pinger = tokio::spawn(ping_loop(link, timeouts.ping_interval));
        TaskManager::instance().add(LINK_TASKS, writer).await;
        TaskManager::instance().add(LINK_TASKS, pinger).await;
        RPC::instance()
            .init(|request| async {
                let data = serde_json::to_string(&AppMessage::Request(request)).unwrap();
                MessageManager::instance()
                    .send(Message::Text(data.into()))
                    .await
            })
            .await;
    }

    /// Gives up on the current connection: process_messages() returns with
    /// this reason, and the caller disposes as after any disconnect.
    pub fn cancel(&self, reason: &str) {
        if let Some(link) = self.link.lock().unwrap().clone() {
            link.fail(reason);
        }
    }

    pub async fn dispose(&self) {
        let link = self.link.lock().unwrap().take();
        if let Some(link) = link {
            link.fail("disposed");
        }
        // Aborting the writer drops the socket even if a write is stuck.
        TaskManager::instance().dispose(LINK_TASKS).await;
        *self.reader.lock().await = None;
        RPC::instance().dispose().await;
        TaskManager::instance().dispose("MessageManager").await;
    }

    /// Queues a control message; it is sent before any queued stream.
    pub async fn send(&self, msg: Message) -> Result<(), AppError> {
        self.current_link()?
            .push(|outbox| Outbox::push_bounded(&mut outbox.control, msg))?;
        Ok(())
    }

    pub async fn send_event(&self, event: &str, data: Option<Value>) -> Result<(), AppError> {
        let event: Event = Event::new(event, data);
        let data = serde_json::to_string(&AppMessage::Event(event)).unwrap();
        MessageManager::instance()
            .send(Message::Text(data.into()))
            .await
    }

    /// Queues a stream that must arrive complete, such as playback audio.
    pub async fn send_stream(
        &self,
        tag: &str,
        bytes: Vec<u8>,
        data: Option<Value>,
    ) -> Result<(), AppError> {
        let frame = Message::Binary(Stream::new(tag, bytes, data).encode().into());
        self.current_link()?
            .push(|outbox| Outbox::push_bounded(&mut outbox.bulk, frame))?;
        Ok(())
    }

    /// Queues live audio without waiting for the network. When the link falls
    /// behind, the oldest queued frames are dropped; returns how many.
    pub async fn send_stream_realtime(
        &self,
        tag: &str,
        bytes: Vec<u8>,
        data: Option<Value>,
    ) -> Result<usize, AppError> {
        let frame = Message::Binary(Stream::new(tag, bytes, data).encode().into());
        Ok(self
            .current_link()?
            .push(|outbox| Ok(outbox.push_realtime(frame)))?)
    }

    pub async fn process_messages(&self) -> Result<(), AppError> {
        let link = self.current_link()?;
        let idle_timeout = self.timeouts.lock().unwrap().idle_timeout;
        let mut reader = self.reader.lock().await;
        let Some(reader) = reader.as_mut() else {
            return Err("WebSocket reader is not initialized".into());
        };

        loop {
            if let Some(reason) = link.failure() {
                return Err(reason.into());
            }
            let next = tokio::select! {
                _ = link.stop.notified() => continue,
                next = timeout(idle_timeout, reader.next()) => next,
            };
            match next {
                Err(_) => {
                    let reason = format!("nothing received for {}s", idle_timeout.as_secs());
                    link.fail(&reason);
                    return Err(reason.into());
                }
                Ok(None) | Ok(Some(Ok(Message::Close(_)))) => break,
                Ok(Some(Err(e))) => return Err(e.into()),
                Ok(Some(Ok(Message::Text(text)))) => {
                    let _ = self.on_text(text.to_string()).await;
                }
                Ok(Some(Ok(Message::Binary(bytes)))) => {
                    let _ = self.on_bytes(bytes.into()).await;
                }
                // Pings and pongs only show that the link is alive.
                Ok(Some(Ok(_))) => {}
            }
        }

        Ok(())
    }

    async fn on_bytes(&self, bytes: Vec<u8>) -> Result<(), AppError> {
        let data = Stream::decode(&bytes)?;
        MessageHandler::<Stream>::instance().on(data).await
    }

    async fn on_text(&self, text: String) -> Result<(), AppError> {
        let msg = serde_json::from_str::<AppMessage>(&text)?;

        match msg {
            AppMessage::Request(request) => {
                self.run_concurrently(move || {
                    let request = request.clone();
                    async move {
                        MessageHandler::<Request>::instance()
                            .on_request(request)
                            .await?;
                        Ok(())
                    }
                })
                .await
            }
            AppMessage::Response(response) => {
                MessageHandler::<Response>::instance()
                    .on_response(response)
                    .await
            }
            AppMessage::Event(event) => MessageHandler::<Event>::instance().on(event).await,
            _ => Ok(()),
        }
    }

    async fn run_concurrently<F, Fut>(&self, run: F) -> Result<(), AppError>
    where
        F: Fn() -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<(), AppError>> + Send + 'static,
    {
        let permit = match self.semaphore.clone().try_acquire_owned() {
            Ok(permit) => permit,
            Err(_) => self.semaphore.clone().acquire_owned().await?,
        };

        let task = tokio::spawn(async move {
            let _ = run().await;
            drop(permit);
        });

        TaskManager::instance().add("MessageManager", task).await;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{Outbox, REALTIME_QUEUE_FRAMES};
    use tokio_tungstenite::tungstenite::Message;

    fn text(s: &str) -> Message {
        Message::text(s.to_string())
    }

    #[test]
    fn control_goes_before_streams_and_streams_keep_order() {
        let mut outbox = Outbox::default();
        outbox.push_realtime(text("audio1"));
        Outbox::push_bounded(&mut outbox.bulk, text("play1")).unwrap();
        outbox.push_realtime(text("audio2"));
        Outbox::push_bounded(&mut outbox.control, text("reply")).unwrap();
        let order: Vec<_> = std::iter::from_fn(|| outbox.pop())
            .map(|m| m.into_text().unwrap().as_str().to_string())
            .collect();
        assert_eq!(order, ["reply", "play1", "audio1", "audio2"]);
    }

    #[test]
    fn realtime_drops_oldest_beyond_limit() {
        let mut outbox = Outbox::default();
        let dropped: usize = (0..REALTIME_QUEUE_FRAMES + 5)
            .map(|i| outbox.push_realtime(text(&i.to_string())))
            .sum();
        assert_eq!(dropped, 5);
        assert_eq!(outbox.realtime.len(), REALTIME_QUEUE_FRAMES);
        assert_eq!(outbox.pop().unwrap().into_text().unwrap().as_str(), "5");
    }

    #[test]
    fn lossless_queues_refuse_instead_of_dropping() {
        let mut outbox = Outbox::default();
        for i in 0..super::QUEUE_LIMIT {
            Outbox::push_bounded(&mut outbox.control, text(&i.to_string())).unwrap();
        }
        assert!(Outbox::push_bounded(&mut outbox.control, text("more")).is_err());
        assert_eq!(outbox.control.len(), super::QUEUE_LIMIT);
    }
}
