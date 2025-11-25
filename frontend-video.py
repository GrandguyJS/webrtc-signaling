import asyncio
import json
import websockets

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.contrib.media import MediaPlayer, MediaRecorder
from aiortc.sdp import candidate_from_sdp

import pyaudio
import numpy as np


WS_URL = "ws://localhost:8765"
ws_connection = None

# =====================================================================
#  Audio player
# =====================================================================

class AudioPlayer:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=2,
            rate=48000,
            output=True
        )

    def play(self, frame):
        pcm = frame.to_ndarray()
        self.stream.write(pcm.tobytes())

# =====================================================================
#  WebRTC Client class
# =====================================================================
class WebRTCClient:
    def __init__(self, name):
        self.name = name
        self.pc = None
        self.player = None
        self.pending_ice = []
        self.audio_player = AudioPlayer()

    # ---------------------------------------------------------
    # Create NEW PeerConnection (fixes "RTCPeerConnection is closed")
    # ---------------------------------------------------------
    async def create_pc(self):
        if self.pc:
            try:
                await self.pc.close()
            except:
                pass

        self.pc = RTCPeerConnection()
        self.pc.addTransceiver("audio", direction="recvonly")

        @self.pc.on("track")
        def on_track(track):
            print(f"[{self.name}] Remote track:", track.kind)
            if track.kind == "audio":
                asyncio.create_task(self.play_audio_track(track))
            else:
                print("Remote video track (ignored)")

        @self.pc.on("icecandidate")
        async def on_ice(candidate):
            if candidate:
                await send({
                    "to": "B",
                    "ice": {  # 👈 was "candidate"
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                    },
                })

        print(f"[{self.name}] New PeerConnection created.")

    # ---------------------------------------------------------
    # Add webcam + mic
    # ---------------------------------------------------------
    def add_media_tracks(self):
        print(f"[{self.name}] Opening webcam + microphone...")

        self.player = MediaPlayer(
            "default",
            format="avfoundation",
            options={"framerate": "30", "video_size": "1280x720", "audio_device_index": "default"},
        )

        if self.player.video:
            self.pc.addTrack(self.player.video)
            print("Local video attached.")

        if self.player.audio:
            self.pc.addTrack(self.player.audio)
            print("Local audio attached.")

    # ---------------------------------------------------------
    # Play incoming audio
    # ---------------------------------------------------------
    async def play_audio_track(self, track):
        while True:
            try:
                frame = await track.recv()
            except:
                break
            self.audio_player.play(frame)

    # ---------------------------------------------------------
    # Start offer
    # ---------------------------------------------------------
    async def start_webrtc(self):
        print(f"[{self.name}] Starting WebRTC...")

        await self.create_pc()
        self.add_media_tracks()

        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        await send({
            "from": self.name,
            "to": "B",
            "sdp": {
                "type": self.pc.localDescription.type,
                "sdp": self.pc.localDescription.sdp,
            },
        })

        print(f"[{self.name}] Offer sent.")

    # ---------------------------------------------------------
    # Handle SDP / ICE from remote
    # ---------------------------------------------------------
    async def handle_signal(self, data):
        # remote says "start"
        if data.get("type") == "ready":
            await self.start_webrtc()
            return

        # remote answer
        if "sdp" in data:
            desc = RTCSessionDescription(
                sdp=data["sdp"]["sdp"],
                type=data["sdp"]["type"],
            )
            await self.pc.setRemoteDescription(desc)

            for cand in self.pending_ice:
                await self.pc.addIceCandidate(cand)
            self.pending_ice.clear()

            print(f"[{self.name}] Remote SDP applied.")
            return

        # ICE candidate
        if "ice" in data:
            ice = data["ice"]
            raw = ice["candidate"]

            cand = candidate_from_sdp(raw)

            cand.sdpMid = ice.get("sdpMid")
            cand.sdpMLineIndex = ice.get("sdpMLineIndex")

            if not self.pc.remoteDescription:
                self.pending_ice.append(cand)
            else:
                await self.pc.addIceCandidate(cand)

            print("Remote ICE added.")
            return

# =====================================================================
#  WebSocket functions
# =====================================================================
async def send(data: dict):
    global ws_connection
    while ws_connection is None:
        await asyncio.sleep(0.1)
    await ws_connection.send(json.dumps(data))


async def connect():
    global ws_connection

    while True:
        try:
            print(f"Connecting to {WS_URL}...")
            client = WebRTCClient("A")
            async with websockets.connect(WS_URL) as ws:
                ws_connection = ws
                print("Connected to signaling server.")

                # identify
                await send({"id": "A"})

                async for msg in ws:
                    data = json.loads(msg)
                    await client.handle_signal(data)

        except Exception as e:
            print("WS lost:", e)

        ws_connection = None
        await asyncio.sleep(3)


# =====================================================================
#  Main
# =====================================================================
async def main():
    await connect()


if __name__ == "__main__":
    asyncio.run(main())
