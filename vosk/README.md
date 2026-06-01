# Vosk Speech-to-Text

Offline, GPU-free speech recognition powered by [Vosk](https://alphacephei.com/vosk/) and [KaldiRecognizer](https://kaldi-asr.org/).

Original implementation: [Sharetape-Speech-To-Text](https://github.com/clint-kristopher-morris/Sharetape-Speech-To-Text) by Clint Kristopher Morris — MIT License.

## What it does

Given a video or WAV audio file, produces:

| Output | Description |
|--------|-------------|
| `words.json` | Every word with start/end timestamps and confidence score |
| `transcript.txt` | Plain-text transcript |
| `captions.srt` | SRT subtitle file ready for video editors |

## Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r vosk/requirements.txt
```

## Download a Vosk model

| Model | Size | Language |
|-------|------|----------|
| [vosk-model-small-ru-0.22](https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip) | 45 MB | 🇷🇺 Russian |
| [vosk-model-small-en-us-0.15](https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip) | 40 MB | 🇺🇸 English |
| [vosk-model-en-us-0.42-gigaspeech](https://alphacephei.com/vosk/models/vosk-model-en-us-0.42-gigaspeech.zip) | 2.3 GB | 🇺🇸 English (HD) |

Unzip the model to `vosk/` (or any path) and pass it via `--model`.

## Usage

**Transcribe a video:**
```bash
python vosk/transcribe.py --video path/to/video.mp4 --model vosk-model-small-en-us-0.15
```

**Transcribe audio only:**
```bash
python vosk/transcribe.py --audio path/to/audio.wav --model vosk-model-small-ru-0.22
```

## Integration with Jarvis Agent

The agent's `pds_ultimate/core/speech_to_text.py` uses Vosk as an **offline fallback** when the primary Grok/Whisper API is unavailable.  Set `STT_BACKEND=vosk` in `.env` to force offline mode and specify the model path:

```env
STT_BACKEND=vosk
VOSK_MODEL_PATH=vosk/vosk-model-small-ru-0.22
```

## Credits

- **Vosk** — https://alphacephei.com/vosk/ (Apache 2.0)
- **KaldiASR** — https://kaldi-asr.org/ (Apache 2.0)
- **Sharetape original** — https://github.com/clint-kristopher-morris/Sharetape-Speech-To-Text (MIT)
