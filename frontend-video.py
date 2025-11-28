import os
from dotenv import load_dotenv
load_dotenv("secret.env")

import requests
import asyncio
import cv2
from livekit import rtc
import sounddevice as sd
import time

SERVER_URL = "wss://live-chat.duckdns.org"
TOKEN_URL = "https://live-chat.duckdns.org/token"
PASSWORD = os.getenv("PASSWORD")
IDENTITY = "usera"
CAMERA = 0

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

async def publish_video(room: rtc.Room, cam_index: int, width=1280, height=720, fps=30):
    capture = cv2.VideoCapture(cam_index)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_FPS, fps)

    source = rtc.VideoSource(width, height)
    track = rtc.LocalVideoTrack.create_video_track("camera", source)

    options = rtc.TrackPublishOptions(
        source=rtc.TrackSource.SOURCE_CAMERA,
        simulcast=True,
        video_encoding=rtc.VideoEncoding(
            max_framerate=fps,
            max_bitrate=2_000_000,
        ),
    )

    await room.local_participant.publish_track(track, options)
    print("Video published.")

    async def draw_frames():
        next_frame = time.perf_counter()

        while True:
            ret, frame = capture.read()
            if not ret:
                continue

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_rgb = cv2.resize(frame_rgb, (width, height))
            data = frame_rgb.tobytes()

            vf = rtc.VideoFrame(
                width,
                height,
                rtc.VideoBufferType.RGB24,
                data
            )

            source.capture_frame(
                vf,
                timestamp_us=time.time_ns() // 1000,
                rotation=rtc.VideoRotation.VIDEO_ROTATION_0
            )

            next_frame += 1 / fps
            await asyncio.sleep(max(0, next_frame - time.perf_counter()))

    asyncio.create_task(draw_frames())

async def main():
    loop = asyncio.get_running_loop()
    room = rtc.Room()

    video_track = None
    if ENABLE_CAMERA:
        cap = cv2.VideoCapture(2)
        if not cap.isOpened():
            print("Cannot open camera")
            return

        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print("Camera resolution:", width, "x", height)
        # Initialize LiveKit video source + track
        video_source = rtc.VideoSource(width, height)
        video_track  = rtc.LocalVideoTrack.create_video_track("camera", video_source)

    # handle remote audio
    @room.on("track_subscribed")
    def on_remote_track(track, pub, participant):
        if isinstance(track, rtc.RemoteAudioTrack):
            print("Subscribed to remote audio")

            stream = rtc.AudioStream.from_track(
                track=track,
                sample_rate=48000,
                num_channels=1,
                loop=loop
            )

            out = sd.OutputStream(
                samplerate=48000,
                channels=1,
                dtype="int16"
            )
            out.start()

            async def audio_reader():
                async for event in stream:
                    frame = event.frame
                    out.write(frame.data)

            asyncio.ensure_future(audio_reader())

    await room.connect(SERVER_URL, get_token())
    # audio
    if ENABLE_MIC:
        audio_source = rtc.AudioSource(48000, 1)
        audio_track  = rtc.LocalAudioTrack.create_audio_track("mic", audio_source)
        await room.local_participant.publish_track(audio_track)
        print("Audio published.")

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

    if ENABLE_CAMERA:
        await room.local_participant.publish_track(video_track)
        print("Video published.")

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
