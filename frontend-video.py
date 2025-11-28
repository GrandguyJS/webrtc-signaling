import os
from dotenv import load_dotenv
load_dotenv("secret.env")

import requests
import asyncio
import cv2
from livekit import rtc
import numpy as np
import sounddevice as sd

SERVER_URL = "wss://live-chat.duckdns.org"
TOKEN_URL = "https://live-chat.duckdns.org/token"
PASSWORD = os.getenv("PASSWORD")
IDENTITY = "usera"

ENABLE_CAMERA = True
ENABLE_MIC = True

def get_token():
    params = {
        "pwd": PASSWORD,
        "identity": IDENTITY
    }
    r = requests.get(TOKEN_URL, params=params)
    data = r.json()
    if "error" in data:
        raise Exception("Wrong password or server rejected authentication")
    return data["token"]

async def main():
    room = rtc.Room()
    await room.connect(SERVER_URL, get_token())

    loop = asyncio.get_running_loop()

    # video: detect camera resolution
    cap = cv2.VideoCapture(0)
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    print("Using camera resolution:", width, "x", height)

    # video
    video_source = rtc.VideoSource(width, height)
    video_track = rtc.LocalVideoTrack.create_video_track("camera", video_source)
    await room.local_participant.publish_track(video_track)
    print("Video published.")

    # audio
    audio_source = rtc.AudioSource(48000, 1)
    audio_track  = rtc.LocalAudioTrack.create_audio_track("mic", audio_source)
    await room.local_participant.publish_track(audio_track)
    print("Audio published.")

    # handle remote audio
    @room.on("track_subscribed")
    def on_track(track, pub, participant):
        if isinstance(track, rtc.RemoteAudioTrack):
            out = sd.OutputStream(
                samplerate=48000,
                channels=1,
                dtype="int16"
            )
            out.start()

            @track.on("data_received")
            def on_audio_frame(frame: rtc.AudioFrame):
                out.write(frame.data)


    # capture video + audio input
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Cannot open camera")
        return

    def audio_callback(indata, frames, time, status):
        # indata is already int16 PCM
        pcm_bytes = indata.tobytes()

        af = rtc.AudioFrame(
            data=pcm_bytes,
            sample_rate=48000,
            num_channels=1,
            samples_per_channel=frames,
        )
        loop.call_soon_threadsafe(
            asyncio.create_task,
            audio_source.capture_frame(af)
        ) 

    sd.InputStream(
        samplerate=48000,
        channels=1,
        dtype="int16",
        blocksize=480,
        callback=audio_callback
    ).start()

    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        vf = rtc.VideoFrame(
            width=rgb.shape[1],
            height=rgb.shape[0],
            type=rtc.VideoBufferType.RGB24,
            data=rgb.tobytes(),
        )

        video_source.capture_frame(
            vf,
            timestamp_us=0,
            rotation=rtc.VideoRotation.VIDEO_ROTATION_0,
        )

        await asyncio.sleep(0)
    


if __name__ == "__main__":
    asyncio.run(main())
