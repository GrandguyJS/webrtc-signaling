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
import glob

SERVER_URL = "wss://live-chat.duckdns.org"
API = "https://live-chat.duckdns.org"
PASSWORD = os.getenv("PASSWORD")
IDENTITY = "usera"
CAMERA = 0

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
    subprocess.run(["pkill", "-USR1", "rpicam-still"])
    for _ in range(10):
        files = glob.glob("tmp/*.jpg")
        if files:
            break
        await asyncio.sleep(1)

    file_name = max(files, key=os.path.getmtime)
    print("Sending " + file_name)
    
    if not files:
        return json.dumps({"ok": False, "error": "no image captured"})
        
    requests.post(
        API + "/upload-image",
        files={"file": open(file_name, "rb")},
        timeout=5,
    )
    
    for file in files:
        os.remove(file)

    await room.local_participant.perform_rpc(
        destination_identity=caller,
        method="image-done",
        payload=json.dumps({"ok": True}),
    )

async def main():
    room = rtc.Room()

    player = devices.open_output()

    # handle remote audio
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

    @room.local_participant.register_rpc_method("image")
    async def rpc_image(data: rtc.RpcInvocationData):
        caller = data.caller_identity

        asyncio.create_task(publish_image(room, caller))
        # return immediately to avoid RPC timeout
        return json.dumps({"ok": True})
    
    try:
        await player.start()
        print("Starting playback!")
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass

    print("Shutting down…")
    await player.aclose()
    await room.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
