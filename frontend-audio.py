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
IDENTITY = "userb"
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

async def main():
    loop = asyncio.get_running_loop()
    try:
        room = rtc.Room()

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
            
            async def stream_audio():
                with sd.InputStream(
                    samplerate=48000,
                    channels=1,
                    dtype='int16',
                    blocksize=1024
                ) as stream:
                    while True:
                        data, _ = stream.read(1024)
                        pcm_bytes = data.tobytes()

                        af = rtc.AudioFrame(
                            data=pcm_bytes,
                            sample_rate=48000,
                            num_channels=1,
                            samples_per_channel=1024,
                        )

                        loop.call_soon_threadsafe(
                            asyncio.create_task,
                            audio_source.capture_frame(af)
                        )
                        await asyncio.sleep(1024 / 48000)
            
            asyncio.create_task(stream_audio())
        
        if play_audio:
            print("Starting playback!")
            await player.start()

        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down…")
        await player.aclose()
        try:
            await room.disconnect()
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())
