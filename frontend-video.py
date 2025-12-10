import os
from dotenv import load_dotenv
load_dotenv("secret.env")

import requests
import asyncio
from livekit import rtc
import sounddevice as sd

import subprocess
import json
from picamzero import Camera

SERVER_URL = "wss://live-chat.duckdns.org"
TOKEN_URL = "https://live-chat.duckdns.org/token"
PASSWORD = os.getenv("PASSWORD")
IDENTITY = "usera"
CAMERA = 0

cam = Camera()

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

class RemoteAudioHandler:
    def __init__(self, loop):
        self.loop = loop
        self.stream = None
        self.out = None
        self.task = None
        self.buffer = None

    def start(self, track):
        self.stop()

        self.stream = rtc.AudioStream.from_track(
            track=track,
            sample_rate=48000,
            num_channels=1,
            loop=self.loop
        )

        # Larger blocksize prevents underruns
        self.out = sd.OutputStream(
            samplerate=48000,
            channels=1,
            dtype="int16",
            blocksize=960,      # 20ms
            latency='low'
        )
        self.out.start()

        from collections import deque
        self.buffer = deque(maxlen=5)  # 100ms buffer

        async def reader():
            async for event in self.stream:
                self.buffer.append(event.frame.data)
                if len(self.buffer) >= 2:
                    try:
                        self.out.write(self.buffer.popleft())
                    except sd.PortAudioError:
                        pass

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

async def main():
    loop = asyncio.get_running_loop()
    room = rtc.Room()

    audio_handler = RemoteAudioHandler(loop)

    # handle remote audio
    @room.on("track_subscribed")
    def on_remote_track(track, pub, participant):
        if isinstance(track, rtc.RemoteAudioTrack):
            print("Subscribed to remote audio")
            audio_handler.start(track)

    @room.on("track_unsubscribed")
    def on_track_unsubscribed(track, pub, participant):
        audio_handler.stop()

    await room.connect(SERVER_URL, get_token())

    @room.local_participant.register_rpc_method("image")
    async def rpc_image(data: rtc.RpcInvocationData):
        caller = data.caller_identity
        cam.take_photo(f"image.jpg")
        await room.local_participant.send_file(
            file_path="image.jpg",
            destination_identities=[caller],
            topic="image",
        )
        # return immediately to avoid RPC timeout
        return json.dumps({"ok": True})
    
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
