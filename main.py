import asyncio
import websockets
import json

clients = {}   # id → websocket
pair = {}      # id → other id

async def handler(ws):
    # first message must set the client ID ("A" or "B")
    init = json.loads(await ws.recv())
    cid = init["id"]
    clients[cid] = ws
    print(f"{cid} connected")

    try:
        async for msg in ws:
            data = json.loads(msg)
            target = data.get("to")
            if "to" in data and target in clients:
                await clients[target].send(msg)
    except:
        pass
    finally:
        print(f"{cid} disconnected")
        del clients[cid]

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("Signaling server running on ws://0.0.0.0:8765")
        await asyncio.Future()

asyncio.run(main())
