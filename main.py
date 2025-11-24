import asyncio
import websockets
import json

clients = {}   # id → websocket

async def handler(ws):
    # first message must set the client ID ("A" or "B")
    init = json.loads(await ws.recv())
    cid = init["id"]
    clients[cid] = ws
    print(f"{cid} connected")
    if "A" in clients and "B" in clients:
        await clients["A"].send(json.dumps({"type": "ready"}))

    try:
        async for msg in ws:
            data = json.loads(msg)
            print(data)
            target = data.get("to")
            if target in clients:
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
