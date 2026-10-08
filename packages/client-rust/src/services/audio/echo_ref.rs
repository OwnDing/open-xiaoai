use serde::{Deserialize, Serialize};

use crate::base::AppError;

use super::config::AudioConfig;

/// Record one microphone together with the speaker's own playback, so the
/// server can cancel the echo and keep listening while the speaker talks.
///
/// On the OH2P, `hw:0,3` (shared as `Capture`) carries three microphones and,
/// on channel 3, a hardware loopback of what is being played, sample-aligned
/// with the microphones. Sent next to an `AudioConfig` as `echo_ref`; clients
/// that do not know it ignore it and keep recording `AudioConfig.pcm`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EchoRefConfig {
    /// Raw multichannel capture device, S32_LE.
    pub pcm: String,
    pub channels: u16,
    /// Capture rate; must be 3x the outgoing `AudioConfig.sample_rate`.
    pub sample_rate: u32,
    pub mic_channel: u16,
    pub ref_channel: u16,
    /// Right shifts from the S32 capture to the S16 wire format. Microphone
    /// data reaches about 2^28 near a loud speaker; the loopback is 24-bit
    /// left-aligned and reaches about 2^30 at volume 75.
    pub mic_shift: u32,
    pub ref_shift: u32,
}

/// Decimation is done here with the low-pass the offline test used:
/// scipy.signal.firwin(61, 1/3, window=("kaiser", 5.0)).
pub const DECIMATION: usize = 3;
const TAPS: usize = 61;
const FIR: [f32; TAPS] = [
    0.000000000e+00, -5.075758102e-04, -7.171615080e-04, 0.000000000e+00,
    1.275830928e-03, 1.636325754e-03, 0.000000000e+00, -2.551690208e-03,
    -3.121165908e-03, 0.000000000e+00, 4.526422701e-03, 5.382747080e-03,
    0.000000000e+00, -7.467288594e-03, -8.729113144e-03, 0.000000000e+00,
    1.180763646e-02, 1.369067031e-02, 0.000000000e+00, -1.839848841e-02,
    -2.138582964e-02, 0.000000000e+00, 2.934103841e-02, 3.484133880e-02,
    0.000000000e+00, -5.182809185e-02, -6.626323878e-02, 0.000000000e+00,
    1.365522151e-01, 2.751477227e-01, 3.335353912e-01, 2.751477227e-01,
    1.365522151e-01, 0.000000000e+00, -6.626323878e-02, -5.182809185e-02,
    0.000000000e+00, 3.484133880e-02, 2.934103841e-02, 0.000000000e+00,
    -2.138582964e-02, -1.839848841e-02, 0.000000000e+00, 1.369067031e-02,
    1.180763646e-02, 0.000000000e+00, -8.729113144e-03, -7.467288594e-03,
    0.000000000e+00, 5.382747080e-03, 4.526422701e-03, 0.000000000e+00,
    -3.121165908e-03, -2.551690208e-03, 0.000000000e+00, 1.636325754e-03,
    1.275830928e-03, 0.000000000e+00, -7.171615080e-04, -5.075758102e-04,
    0.000000000e+00,
];

impl EchoRefConfig {
    pub fn validate(&self, wire: &AudioConfig) -> Result<(), AppError> {
        if wire.bits_per_sample != 16 || wire.channels != 1 {
            return Err("echo_ref needs a mono S16 AudioConfig".into());
        }
        if self.sample_rate != wire.sample_rate * DECIMATION as u32 {
            return Err(format!(
                "echo_ref.sample_rate must be {}x the AudioConfig sample_rate",
                DECIMATION
            )
            .into());
        }
        if self.mic_channel >= self.channels || self.ref_channel >= self.channels {
            return Err("echo_ref channel index out of range".into());
        }
        if self.mic_shift > 31 || self.ref_shift > 31 {
            return Err("echo_ref shift out of range".into());
        }
        Ok(())
    }

    /// What arecord opens: same buffer durations as the wire config.
    pub fn capture_config(&self, wire: &AudioConfig) -> AudioConfig {
        let ratio = DECIMATION as u32;
        AudioConfig {
            pcm: self.pcm.clone(),
            channels: self.channels,
            bits_per_sample: 32,
            sample_rate: self.sample_rate,
            period_size: wire.period_size * ratio,
            buffer_size: wire.buffer_size * ratio,
        }
    }
}

/// Turns S32 multichannel capture into S16 stereo frames [mic, ref] at a
/// third of the rate. Both channels go through the same filter, so the
/// server sees the echo path unchanged.
pub struct EchoRefDecimator {
    channels: usize,
    mic_channel: usize,
    ref_channel: usize,
    mic_scale: f32,
    ref_scale: f32,
    mic: Vec<f32>,
    reference: Vec<f32>,
    /// Index (in `mic`) of the newest input sample of the next output.
    next: usize,
}

impl EchoRefDecimator {
    pub fn new(config: &EchoRefConfig) -> Self {
        Self {
            channels: config.channels as usize,
            mic_channel: config.mic_channel as usize,
            ref_channel: config.ref_channel as usize,
            mic_scale: 1.0 / (1u64 << config.mic_shift) as f32,
            ref_scale: 1.0 / (1u64 << config.ref_shift) as f32,
            mic: vec![0.0; TAPS - 1],
            reference: vec![0.0; TAPS - 1],
            next: TAPS - 1,
        }
    }

    pub fn process(&mut self, chunk: &[u8]) -> Vec<u8> {
        let frame_bytes = 4 * self.channels;
        for frame in chunk.chunks_exact(frame_bytes) {
            let sample = |channel: usize| {
                let at = channel * 4;
                i32::from_le_bytes([frame[at], frame[at + 1], frame[at + 2], frame[at + 3]]) as f32
            };
            self.mic.push(sample(self.mic_channel));
            self.reference.push(sample(self.ref_channel));
        }

        let mut out = Vec::with_capacity((self.mic.len() / DECIMATION + 1) * 4);
        while self.next < self.mic.len() {
            let start = self.next + 1 - TAPS;
            let mic = dot(&self.mic[start..=self.next]) * self.mic_scale;
            let reference = dot(&self.reference[start..=self.next]) * self.ref_scale;
            out.extend_from_slice(&to_i16(mic).to_le_bytes());
            out.extend_from_slice(&to_i16(reference).to_le_bytes());
            self.next += DECIMATION;
        }

        let keep_from = self.next + 1 - TAPS;
        self.mic.drain(..keep_from);
        self.reference.drain(..keep_from);
        self.next -= keep_from;
        out
    }
}

fn dot(samples: &[f32]) -> f32 {
    samples.iter().zip(FIR.iter()).map(|(s, h)| s * h).sum()
}

fn to_i16(value: f32) -> i16 {
    value.round().clamp(i16::MIN as f32, i16::MAX as f32) as i16
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> EchoRefConfig {
        EchoRefConfig {
            pcm: "Capture".into(),
            channels: 4,
            sample_rate: 48000,
            mic_channel: 0,
            ref_channel: 3,
            mic_shift: 14,
            ref_shift: 16,
        }
    }

    fn wire() -> AudioConfig {
        AudioConfig {
            pcm: "noop".into(),
            channels: 1,
            bits_per_sample: 16,
            sample_rate: 16000,
            period_size: 360,
            buffer_size: 1440,
        }
    }

    fn capture(frames: &[[i32; 4]]) -> Vec<u8> {
        frames
            .iter()
            .flat_map(|frame| frame.iter().flat_map(|s| s.to_le_bytes()))
            .collect()
    }

    fn decode(out: &[u8]) -> Vec<(i16, i16)> {
        out.chunks_exact(4)
            .map(|f| {
                (
                    i16::from_le_bytes([f[0], f[1]]),
                    i16::from_le_bytes([f[2], f[3]]),
                )
            })
            .collect()
    }

    #[test]
    fn filter_has_unity_dc_gain() {
        let sum: f32 = FIR.iter().sum();
        assert!((sum - 1.0).abs() < 1e-5);
    }

    #[test]
    fn picks_mic_and_reference_channels_and_scales_them() {
        let mut decimator = EchoRefDecimator::new(&config());
        // Constant input: after the filter has filled, output = input >> shift.
        let frames = vec![[1 << 20, 7, 7, 1 << 24]; 300];
        let out = decode(&decimator.process(&capture(&frames)));
        assert_eq!(out.len(), 100);
        let (mic, reference) = *out.last().unwrap();
        assert_eq!(mic, 1 << 6);
        assert_eq!(reference, 1 << 8);
    }

    #[test]
    fn output_count_does_not_depend_on_chunking() {
        let frames: Vec<[i32; 4]> = (0..999).map(|i| [i * 1000, 0, 0, -i * 1000]).collect();
        let whole = EchoRefDecimator::new(&config()).process(&capture(&frames));
        let mut split = EchoRefDecimator::new(&config());
        let mut pieces = Vec::new();
        for part in frames.chunks(37) {
            pieces.extend(split.process(&capture(part)));
        }
        assert_eq!(whole, pieces);
        assert_eq!(whole.len(), 333 * 4);
    }

    #[test]
    fn removes_content_above_the_new_nyquist() {
        // 12 kHz at 48 kHz would alias to 4 kHz after decimation.
        let tone: Vec<[i32; 4]> = (0..4800)
            .map(|i| {
                let v = ((i as f64) * std::f64::consts::PI / 2.0).sin() * (1 << 26) as f64;
                [v as i32, 0, 0, 0]
            })
            .collect();
        let out = decode(&EchoRefDecimator::new(&config()).process(&capture(&tone)));
        let peak = out[100..].iter().map(|(m, _)| m.unsigned_abs()).max().unwrap();
        // Unfiltered it would peak at 2^26 >> 14 = 4096.
        assert!(peak < 4096 / 30, "peak {peak}");
    }

    #[test]
    fn clamps_instead_of_wrapping() {
        let frames = vec![[i32::MAX, 0, 0, i32::MIN]; 300];
        let out = decode(&EchoRefDecimator::new(&config()).process(&capture(&frames)));
        assert_eq!(*out.last().unwrap(), (i16::MAX, i16::MIN));
    }

    #[test]
    fn validates_rates_channels_and_wire_format() {
        assert!(config().validate(&wire()).is_ok());
        let mut bad = config();
        bad.sample_rate = 44100;
        assert!(bad.validate(&wire()).is_err());
        let mut bad = config();
        bad.ref_channel = 4;
        assert!(bad.validate(&wire()).is_err());
        let mut stereo = wire();
        stereo.channels = 2;
        assert!(config().validate(&stereo).is_err());
        let capture = config().capture_config(&wire());
        assert_eq!((capture.sample_rate, capture.channels, capture.bits_per_sample), (48000, 4, 32));
        assert_eq!((capture.period_size, capture.buffer_size), (1080, 4320));
    }
}
