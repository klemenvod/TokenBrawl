from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional
import random


class Cell(IntEnum):
    FLOOR = 0
    WALL = 1
    BRICK = 2


@dataclass
class Player:
    id: str                    # "p1" or "p2"
    pos: list[int]             # [x, y]
    alive: bool = True
    score: int = 0
    blast_radius: int = 2


@dataclass
class Bomb:
    pos: list[int]             # [x, y]
    owner: str                 # "p1" or "p2"
    fuse_ticks: int = 30       # 3 seconds at 10 ticks/s
    blast_radius: int = 2


@dataclass
class Explosion:
    cells: list[list[int]]     # list of [x, y]
    ttl_ticks: int = 5         # 0.5 seconds


@dataclass
class GameState:
    grid: list[list[int]]      # grid[y][x], 15 wide x 13 tall
    players: dict[str, Player]
    bombs: list[Bomb] = field(default_factory=list)
    explosions: list[Explosion] = field(default_factory=list)
    bricks_remaining: int = 0
    total_bricks: int = 0
    tick: int = 0
    time_remaining_ticks: int = 1800   # 3 min at 10 ticks/s
    game_over: bool = False
    winner: Optional[str] = None
    win_reason: Optional[str] = None   # "bricks" | "kill" | "timer"
    agent_thoughts: dict[str, str] = field(default_factory=dict)
    agent_last_action: dict[str, str] = field(default_factory=dict)
    agent_thinking: dict[str, bool] = field(default_factory=lambda: {"p1": False, "p2": False})
    agent_moving: dict[str, bool] = field(default_factory=lambda: {"p1": False, "p2": False})
    agent_target: dict = field(default_factory=dict)  # {pid: {"pos": [x,y], "bomb": bool} | None}
    agent_action_history: dict[str, list] = field(default_factory=lambda: {"p1": [], "p2": []})
    death_log: dict[str, list] = field(default_factory=dict)
    agent_prompt_input: dict[str, str] = field(default_factory=dict)
    agent_prompt_output: dict[str, str] = field(default_factory=dict)


def create_initial_state() -> GameState:
    WIDTH, HEIGHT = 15, 13
    grid = [[Cell.FLOOR] * WIDTH for _ in range(HEIGHT)]

    # Place border and fixed internal walls
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if x == 0 or x == WIDTH - 1 or y == 0 or y == HEIGHT - 1:
                grid[y][x] = Cell.WALL
            elif x % 2 == 0 and y % 2 == 0:
                grid[y][x] = Cell.WALL

    # Collect eligible cells for bricks
    spawn_zones = set()
    for dy in range(3):
        for dx in range(3):
            spawn_zones.add((1 + dx, 1 + dy))
            spawn_zones.add((13 - dx, 11 - dy))

    eligible = [
        (x, y)
        for y in range(HEIGHT)
        for x in range(WIDTH)
        if grid[y][x] == Cell.FLOOR and (x, y) not in spawn_zones
    ]

    # Place 21 bricks ensuring connectivity
    random.shuffle(eligible)
    brick_cells = set()
    for (x, y) in eligible:
        if len(brick_cells) >= 21:
            break
        grid[y][x] = Cell.BRICK
        brick_cells.add((x, y))
        # connectivity check — BFS from (1,1) treating bricks as passable
        if not _connected(grid, (1, 1), (13, 11), WIDTH, HEIGHT):
            grid[y][x] = Cell.FLOOR
            brick_cells.discard((x, y))

    players = {
        "p1": Player(id="p1", pos=[1, 1]),
        "p2": Player(id="p2", pos=[13, 11]),
    }

    return GameState(
        grid=grid,
        players=players,
        bricks_remaining=len(brick_cells),
        total_bricks=len(brick_cells),
    )


def _connected(grid, start, end, W, H):
    """BFS treating FLOOR and BRICK as passable, WALL as blocked."""
    visited = set()
    queue = [start]
    visited.add(start)
    while queue:
        x, y = queue.pop(0)
        if (x, y) == end:
            return True
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in visited:
                if grid[ny][nx] != Cell.WALL:
                    visited.add((nx, ny))
                    queue.append((nx, ny))
    return False
