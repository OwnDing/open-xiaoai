use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

#[derive(Debug, Serialize, Deserialize)]
pub enum AppMessage {
    Request(Request),
    Response(Response),
    Event(Event),
    Stream(Stream),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Stream {
    pub id: String,
    pub tag: String,
    pub bytes: Vec<u8>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub data: Option<Value>,
}

/// Binary stream frame: `OXS1`, header length (u32 LE), JSON header, raw bytes.
/// The old frame was the whole Stream as JSON, `bytes` as an array of numbers,
/// about three times the payload size; decode() still accepts it.
const STREAM_MAGIC: &[u8; 4] = b"OXS1";

#[derive(Serialize)]
struct StreamHeaderRef<'a> {
    id: &'a str,
    tag: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    data: &'a Option<Value>,
}

#[derive(Deserialize)]
struct StreamHeader {
    id: String,
    tag: String,
    #[serde(default)]
    data: Option<Value>,
}

impl Stream {
    pub fn new(tag: &str, bytes: Vec<u8>, data: Option<Value>) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            tag: tag.to_string(),
            bytes,
            data,
        }
    }

    pub fn encode(&self) -> Vec<u8> {
        let header = serde_json::to_vec(&StreamHeaderRef {
            id: &self.id,
            tag: &self.tag,
            data: &self.data,
        })
        .unwrap();
        let mut frame = Vec::with_capacity(8 + header.len() + self.bytes.len());
        frame.extend_from_slice(STREAM_MAGIC);
        frame.extend_from_slice(&(header.len() as u32).to_le_bytes());
        frame.extend_from_slice(&header);
        frame.extend_from_slice(&self.bytes);
        frame
    }

    pub fn decode(frame: &[u8]) -> Result<Self, String> {
        if frame.len() < 8 || &frame[..4] != STREAM_MAGIC {
            return serde_json::from_slice(frame).map_err(|e| e.to_string());
        }
        let len = u32::from_le_bytes([frame[4], frame[5], frame[6], frame[7]]) as usize;
        let body = &frame[8..];
        if len > body.len() {
            return Err("truncated stream header".into());
        }
        let header: StreamHeader = serde_json::from_slice(&body[..len]).map_err(|e| e.to_string())?;
        Ok(Self {
            id: header.id,
            tag: header.tag,
            bytes: body[len..].to_vec(),
            data: header.data,
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    pub id: String,
    pub event: String,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub data: Option<Value>,
}

impl Event {
    pub fn new(event: &str, data: Option<Value>) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            event: event.to_string(),
            data,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Request {
    pub id: String,
    pub command: String,
    pub payload: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Response {
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub code: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub msg: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub data: Option<Value>,
}

impl Response {
    pub fn success() -> Self {
        Self {
            id: 0.to_string(),
            code: Some(0),
            msg: Some("success".to_string()),
            data: None,
        }
    }

    pub fn from_data(data: Value) -> Self {
        Self {
            id: 0.to_string(),
            code: None,
            msg: None,
            data: Some(data),
        }
    }

    pub fn from_error(id: &str, e: impl std::fmt::Display) -> Self {
        Self {
            id: id.to_string(),
            code: Some(-1),
            msg: Some(e.to_string()),
            data: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::Stream;
    use serde_json::json;

    fn pcm() -> Vec<u8> {
        (0..2880u32).map(|i| (i * 37 % 256) as u8).collect()
    }

    #[test]
    fn binary_frame_round_trips() {
        let stream = Stream::new("record", pcm(), Some(json!({"seq": 7, "capture_id": "abc"})));
        let decoded = Stream::decode(&stream.encode()).unwrap();
        assert_eq!(decoded.id, stream.id);
        assert_eq!(decoded.tag, "record");
        assert_eq!(decoded.bytes, stream.bytes);
        assert_eq!(decoded.data, stream.data);
        let bare = Stream::decode(&Stream::new("play", vec![1, 2, 3], None).encode()).unwrap();
        assert_eq!((bare.bytes, bare.data), (vec![1, 2, 3], None));
    }

    #[test]
    fn legacy_json_frames_still_decode() {
        let stream = Stream::new("record", pcm(), Some(json!({"seq": 1})));
        let legacy = serde_json::to_vec(&stream).unwrap();
        let decoded = Stream::decode(&legacy).unwrap();
        assert_eq!(decoded.bytes, stream.bytes);
        assert_eq!(decoded.data, stream.data);
        // The binary frame carries the same packet in a fraction of the bytes.
        assert!(stream.encode().len() * 2 < legacy.len());
    }

    #[test]
    fn truncated_binary_frame_is_an_error() {
        let mut frame = Stream::new("record", pcm(), None).encode();
        frame.truncate(12);
        assert!(Stream::decode(&frame).is_err());
    }
}
