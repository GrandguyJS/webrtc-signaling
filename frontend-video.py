import os
from dotenv import load_dotenv
load_dotenv("secret.env")

import requests
import asyncio
import sounddevice as sd

from livekit import rtc
devices = rtc.MediaDevices()

import json
import subprocess

SERVER_URL = "wss://live-chat.duckdns.org"
API = "https://live-chat.duckdns.org"
PASSWORD = os.getenv("PASSWORD")
IDENTITY = "usera"
CAMERA = 0

publish_audio = True
play_audio = True

def get_token():
    params = {
        "pwd": PASSWORD,
        "identity": IDENTITY
    }
    r = requests.get(API + "/token", params=params)
    data = r.json()
    if "error" in data:
        raise Exception("Wrong password or server rejected authentication")
    return data["token"]

async def publish_image(room, caller):
    file_name = "tmp/image.jpg"

    await asyncio.to_thread(
        lambda: subprocess.run(
            ["rpicam-still", "--immediate", "-o", file_name],
            check=True,
        )
    )

    await asyncio.to_thread(
        lambda: requests.post(
            API + "/upload",
            files={"file": open(file_name, "rb")},
        )
    )

    await asyncio.to_thread(os.remove, file_name)

    await room.local_participant.perform_rpc(
        destination_identity=caller,
        method="upload-done",
        payload=json.dumps({"ok": True}),
    )

async def publish_video(room, caller):
    file_name = f"tmp/video.mp4"

    subprocess.run(
        [
            "rpicam-vid",
            "-t", "10000",                
            "--width", "1280",
            "--height", "720",
            "--framerate", "25",
            "--bitrate", "4000000",
            "--nopreview",
            "-o", file_name,
        ],
        check=True,
    )

    print("Sending " + file_name)

    requests.post(
        API + "/upload",
        files={"file": open(file_name, "rb")},
    )

    os.remove(file_name)

    await room.local_participant.perform_rpc(
        destination_identity=caller,
        method="upload-done",
        payload=json.dumps({"ok": True}),
    )

async def main():
    loop = asyncio.get_running_loop()
    try:
        room = rtc.Room()

        mic = devices.open_input()
        player = devices.open_output()

        @room.on("track_subscribed")
        def on_remote_track(track, pub, participant):
            print("Subscribed to remote track")
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(player.add_track(track))

        @room.on("track_unsubscribed")
        def on_track_unsubscribed(track, pub, participant):
            print("Unsubscribed to remote track")
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(player.remove_track(track))

        await room.connect(SERVER_URL, get_token())

        if publish_audio:
            audio_source = rtc.AudioSource(48000, 1)
            audio_track  = rtc.LocalAudioTrack.create_audio_track("mic", audio_source)
            await room.local_participant.publish_track(audio_track)
            print("Audio published.")

            with sd.InputStream(
                samplerate=48000,
                channels=1,
                dtype='int16',
                blocksize=1024
            ) as stream:
                while True:
                    data, _ = stream.read(1024)
                    pcm_bytes = data.tobytes()

                    # Build LiveKit frame
                    af = rtc.AudioFrame(
                        data=pcm_bytes,
                        sample_rate=48000,
                        num_channels=1,
                        samples_per_channel=1024,
                    )

                    # Inject into LiveKit audio source
                    loop.call_soon_threadsafe(
                        asyncio.create_task,
                        audio_source.capture_frame(af)
                    )
                    # sleep exactly one frame duration
                    await asyncio.sleep(1024 / 48000)

        @room.local_participant.register_rpc_method("image")
        async def rpc_image(data: rtc.RpcInvocationData):
            caller = data.caller_identity

            asyncio.create_task(publish_image(room, caller))
            # return immediately to avoid RPC timeout
            return json.dumps({"ok": True})
        
        @room.local_participant.register_rpc_method("video")
        async def rpc_video(data: rtc.RpcInvocationData):
            caller = data.caller_identity

            asyncio.create_task(publish_video(room, caller))
            # return immediately to avoid RPC timeout
            return json.dumps({"ok": True})
        
        while True:
            if play_audio:
                await player.start()
                print("Starting playback!")
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down…")
        await player.aclose()
        await mic.aclose()
        try:
            await room.disconnect()
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())
