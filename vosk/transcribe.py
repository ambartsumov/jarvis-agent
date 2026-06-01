"""
Vosk Speech-to-Text CLI
=======================
Transcribe a video or WAV audio file to text, word-timestamps, and SRT captions.

Original: https://github.com/clint-kristopher-morris/Sharetape-Speech-To-Text (MIT)
"""

import argparse
import logging
import os
import uuid

from vosk import Model, SetLogLevel

from sharetape import Sharetape


def main():
    parser = argparse.ArgumentParser(
        description="Offline STT via Vosk — outputs transcript, word timestamps, and SRT captions."
    )
    parser.add_argument("-v", "--video", type=str, required=False, default="",
                        help="Path to .mp4 / .mov video file")
    parser.add_argument("-a", "--audio", type=str, required=False, default="",
                        help="Path to .wav audio file")
    parser.add_argument("-m", "--model", type=str,
                        default="vosk-model-en-us-0.42-gigaspeech",
                        help="Path to unzipped Vosk model directory")
    args = parser.parse_args()

    if not (args.video or args.audio):
        parser.error("No action requested, add --video or --audio")
    elif args.video and args.audio:
        parser.error("Only select one action --video or --audio")

    SetLogLevel(-1)
    model = Model(model_path=args.model)
    logging.info("Vosk model loaded")

    video_id = str(uuid.uuid4())
    os.makedirs(f"{video_id}")

    if args.audio != "":
        audio = args.audio
    else:
        audio = f"{video_id}/audio.wav"

    shartape = Sharetape(
        args.video,
        audio,
        f"{video_id}/mono_audio.wav",
        f"{video_id}/transcript.txt",
        f"{video_id}/words.json",
        f"{video_id}/captions.srt",
        model,
    )
    shartape.extract_transcript()


if __name__ == "__main__":
    main()
