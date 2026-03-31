from .state import GameState, Cell, Bomb
from .pathfinder import get_reachable
from .engine import compute_blast_cells


def _other(player_id: str) -> str:
    return "p2" if player_id == "p1" else "p1"


def _format_time(ticks: int) -> str:
    total_seconds = max(0, ticks) // 10
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _build_ascii_grid(state: GameState, player_id: str, reachable_set: set) -> str:
    """Build ASCII representation of the grid."""
    enemy_id = _other(player_id)
    me = state.players[player_id]
    enemy = state.players[enemy_id]

    # Build sets for quick lookup
    bomb_positions = {}
    for b in state.bombs:
        bomb_positions[(b.pos[0], b.pos[1])] = b.owner

    explosion_set = set()
    for exp in state.explosions:
        for c in exp.cells:
            explosion_set.add((c[0], c[1]))

    lines = []
    H = len(state.grid)
    W = len(state.grid[0])

    for y in range(H):
        row = ""
        for x in range(W):
            pos = (x, y)
            if pos == (me.pos[0], me.pos[1]):
                row += "1"
            elif pos == (enemy.pos[0], enemy.pos[1]):
                row += "2"
            elif pos in explosion_set:
                row += "X"
            elif pos in bomb_positions:
                row += "*" if bomb_positions[pos] == player_id else "!"
            elif state.grid[y][x] == Cell.WALL:
                row += "#"
            elif state.grid[y][x] == Cell.BRICK:
                row += "b"
            elif pos in reachable_set:
                row += "."
            else:
                row += " "
        lines.append(row)

    return "\n".join(lines)


def _build_corridor_text(corridors: list, player_pos: list[int]) -> str:
    """Format corridors as human-readable text."""
    if not corridors:
        return "  No paths available"

    lines = []
    px, py = player_pos

    for corr in corridors:
        cells = corr["cells"]
        cells_str = " ".join(f"({c[0]},{c[1]})" for c in cells)

        if corr["type"] == "row":
            y = corr["index"]
            xs = [c[0] for c in cells]
            if min(xs) > px:
                direction = "East"
            elif max(xs) < px:
                direction = "West"
            else:
                direction = "Along"
            lines.append(f"  -> {direction} along row {y}: {cells_str}")
        else:
            x = corr["index"]
            ys = [c[1] for c in cells]
            if min(ys) > py:
                direction = "South"
            elif max(ys) < py:
                direction = "North"
            else:
                direction = "Along"
            lines.append(f"  -> {direction} along col {x}: {cells_str}")

    return "\n".join(lines)


def _build_brick_targets(state: GameState, player_id: str, reachable_bricks: list, reachable_floor_set: set) -> str:
    """List each reachable brick with a description of what bombing it opens."""
    if not reachable_bricks:
        return "  No bricks in range"

    lines = []
    H = len(state.grid)
    W = len(state.grid[0])

    for brick in reachable_bricks:
        bx, by = brick
        # Hypothetical: what opens if this brick is removed?
        description = _describe_brick_impact(state.grid, bx, by, W, H, reachable_floor_set)
        lines.append(f"  ({bx},{by}) -> {description}")

    return "\n".join(lines)


def _describe_brick_impact(grid, bx, by, W, H, reachable_set) -> str:
    """Describe what removing a brick at (bx,by) would open."""
    # Check directions for new openings
    directions = []

    # Check what's beyond this brick in each direction
    for dx, dy, dir_name in [(1, 0, "east"), (-1, 0, "west"), (0, 1, "south"), (0, -1, "north")]:
        nx, ny = bx + dx, by + dy
        if 0 <= nx < W and 0 <= ny < H:
            cell = grid[ny][nx]
            if cell == Cell.FLOOR and (nx, ny) not in reachable_set:
                directions.append(f"opens path {dir_name}")
            elif cell == Cell.FLOOR and (nx, ny) in reachable_set:
                directions.append(f"connects {dir_name}")
            elif cell == Cell.BRICK:
                directions.append(f"more bricks {dir_name}")

    if directions:
        return ", ".join(directions)
    return "isolated brick"


def _build_bombs_text(state: GameState, player_id: str) -> str:
    """List all active bombs."""
    if not state.bombs:
        return "  No active bombs"

    lines = []
    for b in state.bombs:
        owner_label = "Your bomb" if b.owner == player_id else "Enemy bomb"
        time_left = b.fuse_ticks / 10.0
        blast = compute_blast_cells(state.grid, b)
        blast_str = "".join(f"({c[0]},{c[1]})" for c in blast)
        lines.append(f"  {owner_label} at ({b.pos[0]},{b.pos[1]}) explodes in {time_left:.1f}s")
        lines.append(f"    Blast zone: {blast_str}")

    return "\n".join(lines)


def _build_danger_text(state: GameState, player_id: str, reachable_bricks: list, reachable_floor_set: set) -> str:
    """Pre-compute blast danger for player position and targets, including safe escape cells."""
    if not state.bombs:
        return "  No threats"

    me = state.players[player_id]
    my_pos = (me.pos[0], me.pos[1])

    # Collect ALL blast cells from all active bombs
    all_danger = set()
    for b in state.bombs:
        blast = compute_blast_cells(state.grid, b)
        for c in blast:
            all_danger.add((c[0], c[1]))

    lines = []

    for b in state.bombs:
        blast = compute_blast_cells(state.grid, b)
        blast_set = set((c[0], c[1]) for c in blast)
        owner_label = "Your" if b.owner == player_id else "Enemy"
        time_left = b.fuse_ticks / 10.0

        blast_str = "".join(f"({c[0]},{c[1]})" for c in blast)
        lines.append(f"  {owner_label} bomb at ({b.pos[0]},{b.pos[1]}) explodes in {time_left:.1f}s")
        lines.append(f"    Blast will hit: {blast_str}")

        if my_pos in blast_set:
            lines.append(f"    ⚠ Your position ({my_pos[0]},{my_pos[1]}) is IN DANGER — MOVE NOW!")
        else:
            lines.append(f"    Your position ({my_pos[0]},{my_pos[1]}) is SAFE")

        # Check brick targets in blast zone
        for brick in reachable_bricks:
            bx, by = brick
            if (bx, by) in blast_set:
                lines.append(f"    Target ({bx},{by}) is in blast zone — avoid")

    # Compute safe escape cells: reachable adjacent cells NOT in any blast zone
    safe_cells = []
    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        nx, ny = my_pos[0] + dx, my_pos[1] + dy
        if (nx, ny) in reachable_floor_set and (nx, ny) not in all_danger:
            safe_cells.append((nx, ny))

    if my_pos in all_danger:
        if safe_cells:
            safe_str = " ".join(f"({c[0]},{c[1]})" for c in safe_cells)
            lines.append(f"  SAFE ESCAPE CELLS (move here!): {safe_str}")
        else:
            lines.append(f"  WARNING: No safe adjacent cells! Move further away!")
    else:
        danger_adjacent = [(my_pos[0] + dx, my_pos[1] + dy) for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)] if (my_pos[0]+dx, my_pos[1]+dy) in all_danger]
        if danger_adjacent:
            da_str = " ".join(f"({c[0]},{c[1]})" for c in danger_adjacent)
            lines.append(f"  AVOID THESE CELLS (in blast zone): {da_str}")

    return "\n".join(lines)


def score_situation(state: GameState, player_id: str) -> str:
    enemy_id = _other(player_id)
    me = state.players[player_id].score
    enemy = state.players[enemy_id].score
    diff = me - enemy
    remaining = state.bricks_remaining

    if diff > 0 and remaining < diff:
        return f"You are WINNING by {diff}. Enemy cannot catch up on bricks. Play safe, avoid combat."
    elif diff < 0 and remaining < abs(diff):
        return f"You are LOSING by {abs(diff)} with only {remaining} bricks left. You CANNOT win on bricks. You must kill the enemy to win."
    elif diff < 0:
        return f"You are LOSING by {abs(diff)}. {remaining} bricks remain — you can still catch up."
    elif diff > 0:
        return f"You are WINNING by {diff}. {remaining} bricks remain. Keep farming."
    else:
        return f"Score is TIED. {remaining} bricks remain."


def serialize(state: GameState, player_id: str) -> str:
    """Produce the full LLM prompt from game state."""
    enemy_id = _other(player_id)
    me = state.players[player_id]
    enemy = state.players[enemy_id]

    # Get reachable cells
    reachable = get_reachable(state.grid, me.pos, state.bombs)
    reachable_floor_set = set((c[0], c[1]) for c in reachable["floor"])

    # Build components
    ascii_grid = _build_ascii_grid(state, player_id, reachable_floor_set)
    corridor_text = _build_corridor_text(reachable["corridors"], me.pos)
    brick_targets_text = _build_brick_targets(state, player_id, reachable["bricks"], reachable_floor_set)
    bombs_text = _build_bombs_text(state, player_id)
    danger_text = _build_danger_text(state, player_id, reachable["bricks"], reachable_floor_set)
    score_text = score_situation(state, player_id)
    time_str = _format_time(state.time_remaining_ticks)

    return f"""=== BOMBER-{player_id[-1]} | Tick {state.tick} ===
Score: YOU={me.score}  ENEMY={enemy.score}  |  Bricks remaining: {state.bricks_remaining}  |  Time: {time_str}

MAP (15x13):
{ascii_grid}
Legend: # wall  b brick  . reachable floor  (space)=unreachable  1=you  2=enemy  *=your bomb  !=enemy bomb  X=explosion

REACHABLE PATHS:
{corridor_text}

BRICK TARGETS:
{brick_targets_text}

ACTIVE BOMBS:
{bombs_text}

DANGER:
{danger_text}

SCORE SITUATION:
{score_text}

Choose ONE action. Valid actions:
  - "move"          — move to target: {{"reasoning": "...", "action": "move", "target": [x, y]}}
  - "move_and_bomb" — move to target then place bomb: {{"reasoning": "...", "action": "move_and_bomb", "target": [x, y]}}
  - "bomb_here"     — place bomb at current position: {{"reasoning": "...", "action": "bomb_here"}}
  - "wait"          — stay in place, do nothing: {{"reasoning": "...", "action": "wait"}}
Respond with ONE JSON line only.

Valid actions:
  move          -> move to target, do not place bomb
  move_and_bomb -> move to target, place bomb on arrival
  bomb_here     -> place bomb at current position (no target needed)
  wait          -> do nothing this turn

Rules:
  - Target must be in reachable paths or brick targets list
  - You will die if caught in any blast radius — plan your escape before bombing
  - Killing the enemy wins instantly regardless of score
  - Destroying bricks scores +1 per brick"""
