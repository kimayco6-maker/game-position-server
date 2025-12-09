from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class Player:
    player_id: str
    name: str
    shape: str
    color: str
    x: float
    y: float
    websocket: WebSocket


# rooms[room_id] -> {player_id: Player}
rooms: Dict[str, Dict[str, Player]] = {}
room_locks: Dict[str, asyncio.Lock] = {}


def get_lock(room_id: str) -> asyncio.Lock:
    lock = room_locks.get(room_id)
    if lock is None:
        lock = asyncio.Lock()
        room_locks[room_id] = lock
    return lock


async def send_json(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload))


async def broadcast(room_id: str, payload: dict, skip: Optional[str] = None) -> None:
    # send to everyone in room except "skip"
    players = rooms.get(room_id, {})
    tasks = []
    for pid, p in players.items():
        if skip and pid == skip:
            continue
        tasks.append(send_json(p.websocket, payload))

    if not tasks:
        return

    done, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
    # Cleanup any failed sockets
    failures = []
    for task in done:
        if task.exception():
            try:
                ws = task.get_coro().cr_frame.f_locals.get("ws")  # best-effort
            except Exception:
                ws = None
            failures.append(ws)

    if failures:
        players = rooms.get(room_id, {})
        stale_ids = [pid for pid, p in players.items() if p.websocket in failures]
        for pid in stale_ids:
            players.pop(pid, None)


async def send_state(ws: WebSocket, room_id: str, your_id: str) -> None:
    snapshot = []
    for pid, p in rooms.get(room_id, {}).items():
        snapshot.append(
            {
                "player_id": pid,
                "name": p.name,
                "shape": p.shape,
                "color": p.color,
                "x": p.x,
                "y": p.y,
            }
        )
    await send_json(ws, {"type": "state", "room": room_id, "players": snapshot, "you": your_id})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    room_id: Optional[str] = None
    player_id: Optional[str] = None
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "join":
                room_id = msg.get("room")
                player_id = msg.get("player_id")
                if not room_id or not player_id:
                    await send_json(ws, {"type": "error", "message": "room and player_id required"})
                    continue

                async with get_lock(room_id):
                    players = rooms.setdefault(room_id, {})
                    players[player_id] = Player(
                        player_id=player_id,
                        name=msg.get("name", "player"),
                        shape=msg.get("shape", "square"),
                        color=msg.get("color", "#00ff00"),
                        x=float(msg.get("x", 120)),
                        y=float(msg.get("y", 120)),
                        websocket=ws,
                    )

                await send_state(ws, room_id, player_id)
                await broadcast(
                    room_id,
                    {
                        "type": "update",
                        "player": {
                            "player_id": player_id,
                            "name": msg.get("name", "player"),
                            "shape": msg.get("shape", "square"),
                            "color": msg.get("color", "#00ff00"),
                            "x": msg.get("x", 120),
                            "y": msg.get("y", 120),
                        },
                    },
                    skip=player_id,
                )

            elif msg_type == "update" and room_id and player_id:
                x = float(msg.get("x", 0))
                y = float(msg.get("y", 0))
                async with get_lock(room_id):
                    player = rooms.get(room_id, {}).get(player_id)
                    if player:
                        player.x = x
                        player.y = y
                await broadcast(
                    room_id,
                    {"type": "update", "player": {"player_id": player_id, "x": x, "y": y}},
                    skip=player_id,
                )
    except WebSocketDisconnect:
        pass
    finally:
        if room_id and player_id:
            async with get_lock(room_id):
                players = rooms.get(room_id)
                if players and player_id in players:
                    players.pop(player_id, None)
                    if not players:
                        rooms.pop(room_id, None)
            await broadcast(room_id, {"type": "leave", "player_id": player_id}, skip=None)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=5000, reload=True)

