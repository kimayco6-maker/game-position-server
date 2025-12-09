from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from typing import Dict, List

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# In-memory room store. For production, move to a database.
ROOMS: Dict[str, Dict[str, "Player"]] = {}
PLAYER_TTL = 35  # seconds of inactivity before removal


@dataclass
class Player:
    player_id: str
    name: str
    shape: str
    color: str
    x: float
    y: float
    last_seen: float


def now() -> float:
    return time.time()


def cleanup_room(room_id: str) -> None:
    players = ROOMS.get(room_id)
    if not players:
        return
    cutoff = now() - PLAYER_TTL
    stale = [pid for pid, p in players.items() if p.last_seen < cutoff]
    for pid in stale:
        players.pop(pid, None)
    if not players:
        ROOMS.pop(room_id, None)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/rooms/<room_id>/join", methods=["POST"])
def join_room(room_id: str):
    data = request.get_json(force=True, silent=True) or {}
    player_id = data.get("player_id")
    if not player_id:
        return jsonify({"error": "player_id required"}), 400

    name = data.get("name", "player")
    shape = data.get("shape", "square")
    color = data.get("color", "#00ff00")

    room = ROOMS.setdefault(room_id, {})
    room[player_id] = Player(
        player_id=player_id,
        name=name,
        shape=shape,
        color=color,
        x=data.get("x", 120.0),
        y=data.get("y", 120.0),
        last_seen=now(),
    )
    cleanup_room(room_id)
    return jsonify({"ok": True, "room": room_id})


@app.route("/rooms/<room_id>/update", methods=["POST"])
def update_position(room_id: str):
    data = request.get_json(force=True, silent=True) or {}
    player_id = data.get("player_id")
    if not player_id:
        return jsonify({"error": "player_id required"}), 400
    x = float(data.get("x", 0))
    y = float(data.get("y", 0))

    room = ROOMS.setdefault(room_id, {})
    player = room.get(player_id)
    if not player:
        # Treat as implicit join with defaults
        room[player_id] = Player(
            player_id=player_id,
            name=data.get("name", "player"),
            shape=data.get("shape", "square"),
            color=data.get("color", "#00ff00"),
            x=x,
            y=y,
            last_seen=now(),
        )
    else:
        player.x = x
        player.y = y
        player.last_seen = now()

    cleanup_room(room_id)
    return jsonify({"ok": True})


@app.route("/rooms/<room_id>/state", methods=["GET"])
def room_state(room_id: str):
    player_id = request.args.get("player_id")
    cleanup_room(room_id)
    players = ROOMS.get(room_id, {})
    payload: List[dict] = []
    for pid, player in players.items():
        payload.append(asdict(player))
    return jsonify({"room": room_id, "players": payload, "you": player_id})


@app.route("/rooms/<room_id>/leave", methods=["POST"])
def leave_room(room_id: str):
    data = request.get_json(force=True, silent=True) or {}
    player_id = data.get("player_id")
    if not player_id:
        return jsonify({"error": "player_id required"}), 400
    room = ROOMS.get(room_id)
    if room:
        room.pop(player_id, None)
        if not room:
            ROOMS.pop(room_id, None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

