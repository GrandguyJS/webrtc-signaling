import os
from dotenv import load_dotenv
load_dotenv("secret.env")

import requests
import asyncio
import cv2
from livekit import rtc
import sounddevice as sd
import time

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)

SERVER_URL = "wss://live-chat.duckdns.org"
TOKEN_URL = "https://live-chat.duckdns.org/token"
PASSWORD = os.getenv("PASSWORD")
IDENTITY = "usera"
CAMERA = 0

ENABLE_CAMERA = True

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

async def publish_video(room: rtc.Room, cam_index=0, width=1280, height=720, fps=30):
    # Create encoded video track from GStreamer
    source = rtc.VideoSource(width, height)
    track = rtc.LocalVideoTrack.create_video_track("camera", source)

    await room.local_participant.publish_track(track)
    print("Video published (GStreamer).")

    #
    # ---- GStreamer pipeline ----
    #
    pipeline = Gst.parse_launch(
        "avfvideosrc ! "
        "videoconvert ! video/x-raw,format=I420 ! "
        "appsink name=sink emit-signals=true max-buffers=1 drop=true"
    )
    appsink = pipeline.get_by_name("sink")
    pipeline.set_state(Gst.State.PLAYING)

    print("GStreamer pipeline started.")

    try:
        while True:
            # IMPORTANT: safe pull
            sample = appsink.emit("pull-sample")
            if sample is None:
                await asyncio.sleep(0)
                continue

            buffer = sample.get_buffer()
            caps = sample.get_caps()
            if buffer is None or caps is None:
                break  # pipeline is shutting down → exit safely

            try:
                width = caps.get_structure(0).get_value("width")
                height = caps.get_structure(0).get_value("height")
            except Exception:
                break  # caps invalid → stop before segfault

            ok, mapinfo = buffer.map(Gst.MapFlags.READ)
            if not ok:
                break  # cannot map → end loop safely

            try:
                frame_bytes = mapinfo.data

                frame = rtc.VideoFrame(
                    width=width,
                    height=height,
                    type=rtc.VideoBufferType.I420,
                    data=frame_bytes,
                )
                source.capture_frame(frame)

            finally:
                # ALWAYS unmap even if capture fails
                buffer.unmap(mapinfo)

            await asyncio.sleep(0)

    finally:
        # SAFE CLEANUP → prevents segfaults
        print("Stopping pipeline...")
        pipeline.set_state(Gst.State.NULL)
        del appsink
        del pipeline
        print("Pipeline stopped cleanly.")

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

    # video
    if ENABLE_CAMERA:
        video_task = asyncio.create_task(publish_video(room))
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass

    print("Shutting down…")
    audio_handler.stop()
    if video_task:
        video_task.cancel()
    await room.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
