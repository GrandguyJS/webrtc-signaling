import os
from dotenv import load_dotenv
load_dotenv("secret.env")

import subprocess
import asyncio
import requests
import sounddevice as sd
from livekit import rtc

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
SERVER_URL = "wss://live-chat.duckdns.org"
TOKEN_URL = "https://live-chat.duckdns.org/token"

PASSWORD = os.getenv("PASSWORD")
IDENTITY = "usera"

CAMERA = 0
ENABLE_CAMERA = True

TCP_HOST = "0.0.0.0"
TCP_PORT = 16400


# ---------------------------------------------------------
# Token fetch
# ---------------------------------------------------------
def get_token():
    params = {
        "pwd": PASSWORD,
        "identity": IDENTITY,
    }
    r = requests.get(TOKEN_URL, params=params)
    data = r.json()
    if "error" in data:
        raise Exception("Wrong password or server rejected authentication")
    return data["token"]


# ---------------------------------------------------------
# 1. Start GStreamer pipeline
# ---------------------------------------------------------
def start_gstreamer():
    if not ENABLE_CAMERA:
        print("Camera disabled; not starting GStreamer.")
        return None

    cmd = [
        "gst-launch-1.0",
        "avfvideosrc",
        "!",
        "video/x-raw,width=1280,height=720,framerate=25/1,format=NV12",
        "!",
        "x264enc",
        "tune=zerolatency",
        "bitrate=1500",
        "speed-preset=ultrafast",
        "key-int-max=25",
        "byte-stream=true",
        "threads=1",
        "aud=true",
        "!",
        "video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline",
        "!",
        f"tcpserversink", f"host={TCP_HOST}", f"port={TCP_PORT}"
    ]

    print("Starting GStreamer pipeline...")
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


# ---------------------------------------------------------
# 2. Audio Handler
# ---------------------------------------------------------
class RemoteAudioHandler:
    def __init__(self, loop):
        self.loop = loop
        self.stream = None
        self.out = None
        self.task = None

    def start(self, track):
        # destroy old ones if they exist
        self.stop()

        self.stream = rtc.AudioStream.from_track(
            track=track,
            sample_rate=48000,
            num_channels=1,
            loop=self.loop
        )

        self.out = sd.OutputStream(
            samplerate=48000,
            channels=1,
            dtype="int16"
        )
        self.out.start()

        async def reader():
            async for event in self.stream:
                self.out.write(event.frame.data)

        self.task = asyncio.create_task(reader())

    def stop(self):
        if self.task:
            self.task.cancel()
            self.task = None
        if self.out:
            self.out.stop()
            self.out.close()
            self.out = None
        self.stream = None


# ---------------------------------------------------------
# 3. LiveKit logic
# ---------------------------------------------------------
async def main():
    loop = asyncio.get_running_loop()
    audio_handler = RemoteAudioHandler(loop)
    token = get_token()

    room = rtc.Room()

    @room.on("track_subscribed")
    def on_remote_track(track, pub, participant):
        if isinstance(track, rtc.RemoteAudioTrack):
            print("Subscribed to remote audio")
            audio_handler.start(track)

    @room.on("track_unsubscribed")
    def on_track_unsubscribed(track, pub, participant):
        audio_handler.stop()

    await room.connect(SERVER_URL, token)

    # video
    if ENABLE_CAMERA:
        start_gstreamer()
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass

    print("Shutting down…")
    audio_handler.stop()
    await room.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
