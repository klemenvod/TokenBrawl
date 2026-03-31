import asyncio
import json
import os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import openai

from .game.state import create_initial_state, GameState, Player, Bomb, Explosion
from .game.engine import run_game_loop
from .agents.llm_agent import LLMAgent

# Load .env from project root
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount frontend static files
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

connected_clients: list[WebSocket] = []


def state_to_dict(state: GameState) -> dict:
    """Serialize the full GameState to a JSON-compatible dict."""
    return {
        "grid": state.grid,
        "players": {
            pid: {
                "id": p.id,
                "pos": p.pos,
                "alive": p.alive,
                "score": p.score,
                "blast_radius": p.blast_radius,
            }
            for pid, p in state.players.items()
        },
        "bombs": [
            {
                "pos": b.pos,
                "owner": b.owner,
                "fuse_ticks": b.fuse_ticks,
                "blast_radius": b.blast_radius,
            }
            for b in state.bombs
        ],
        "explosions": [
            {
                "cells": e.cells,
                "ttl_ticks": e.ttl_ticks,
            }
            for e in state.explosions
        ],
        "bricks_remaining": state.bricks_remaining,
        "time_remaining_ticks": state.time_remaining_ticks,
        "tick": state.tick,
        "game_over": state.game_over,
        "winner": state.winner,
        "win_reason": state.win_reason,
        "agent_thoughts": state.agent_thoughts,
        "agent_last_action": state.agent_last_action,
    }


async def broadcast(state: GameState):
    """Serialize state to JSON and send to all connected WebSocket clients."""
    payload = state_to_dict(state)
    msg = json.dumps(payload)
    disconnected = []
    for ws in connected_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in connected_clients:
            connected_clients.remove(ws)


@app.get("/")
async def root():
    return FileResponse(str(frontend_dir / "index.html"))


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive, ignore input
    except WebSocketDisconnect:
        if ws in connected_clients:
            connected_clients.remove(ws)


@app.on_event("startup")
async def startup():
    asyncio.create_task(start_game())


async def start_game():
    await asyncio.sleep(1)  # wait for server to be ready

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_key_here":
        print("WARNING: OPENROUTER_API_KEY not set. Agents will fail.")

    client = openai.AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    state = create_initial_state()
    state_ref = [state]  # mutable container so agents always see latest state

    action_queues = {
        "p1": asyncio.Queue(),
        "p2": asyncio.Queue(),
    }

    agents = {
        "p1": LLMAgent("p1", state_ref, action_queues["p1"], client),
        "p2": LLMAgent("p2", state_ref, action_queues["p2"], client),
    }

    tasks = [
        asyncio.create_task(agents["p1"].run()),
        asyncio.create_task(agents["p2"].run()),
    ]

    await run_game_loop(state_ref, broadcast, action_queues)

    for agent in agents.values():
        agent.stop()
    for task in tasks:
        task.cancel()
