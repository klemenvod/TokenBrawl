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


def _build_blast_shadow(state: GameState) -> set[tuple[int, int]]:
    """Compute the set of all floor/brick cells in any active bomb's blast zone (excluding bomb center)."""
    shadow = set()
    for b in state.bombs:
        blast = compute_blast_cells(state.grid, b)
        bomb_pos = (b.pos[0], b.pos[1])
        for c in blast:
            pos = (c[0], c[1])
            if pos != bomb_pos:
                shadow.add(pos)
    return shadow


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

    blast_shadow = _build_blast_shadow(state)

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
            elif pos in blast_shadow:
                row += "x"
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
    """List each reachable brick with adjacent floor tiles to bomb from, excluding bricks in active blast zones."""
    # Compute all cells in any active bomb's blast zone
    danger = set()
    for b in state.bombs:
        for c in compute_blast_cells(state.grid, b):
            danger.add((c[0], c[1]))

    # Filter out bricks whose "bomb from" positions are all in blast zones
    safe_bricks = []
    for brick in reachable_bricks:
        bx, by = brick
        if (bx, by) in danger:
            continue
        # Check if any adjacent bomb-from tile is safe
        has_safe_spot = False
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = bx + dx, by + dy
            if (nx, ny) in reachable_floor_set and (nx, ny) not in danger:
                has_safe_spot = True
                break
        if has_safe_spot:
            safe_bricks.append(brick)

    if not safe_bricks:
        return "  No safe bricks in range (some targets hidden due to active blast zones)"

    lines = []
    H = len(state.grid)
    W = len(state.grid[0])

    for brick in safe_bricks:
        bx, by = brick
        description = _describe_brick_impact(state.grid, bx, by, W, H, reachable_floor_set)
        # Only show bomb-from positions that are outside blast zones
        bomb_from = []
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = bx + dx, by + dy
            if (nx, ny) in reachable_floor_set and (nx, ny) not in danger:
                bomb_from.append(f"({nx},{ny})")
        bomb_from_str = " ".join(bomb_from) if bomb_from else "none"
        lines.append(f"  brick ({bx},{by}) -> bomb from: {bomb_from_str} | {description}")

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


def _build_bombs_merged(state: GameState, player_id: str, reachable_bricks: list, reachable_floor_set: set) -> str:
    """Single merged bomb section: position, timing, blast, safety assessment."""
    if not state.bombs:
        return "  No active bombs."

    me = state.players[player_id]
    my_pos = (me.pos[0], me.pos[1])

    all_danger = set()
    for b in state.bombs:
        for c in compute_blast_cells(state.grid, b):
            all_danger.add((c[0], c[1]))

    lines = []
    for b in state.bombs:
        blast = compute_blast_cells(state.grid, b)
        blast_set = set((c[0], c[1]) for c in blast)
        owner_label = "YOUR bomb" if b.owner == player_id else "Enemy bomb"
        explodes_at = state.tick + b.fuse_ticks
        blast_str = " ".join(f"({c[0]},{c[1]})" for c in blast)
        lines.append(f"  {owner_label} at ({b.pos[0]},{b.pos[1]}) — explodes tick {explodes_at} ({b.fuse_ticks} ticks / {b.fuse_ticks/10:.1f}s)")
        lines.append(f"    Blast: {blast_str}")
        if my_pos in blast_set:
            lines.append(f"    ⚠ YOU ARE IN THE BLAST ZONE — ESCAPE NOW!")
            safe_cells = [f"({my_pos[0]+dx},{my_pos[1]+dy})"
                          for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)]
                          if (my_pos[0]+dx, my_pos[1]+dy) in reachable_floor_set
                          and (my_pos[0]+dx, my_pos[1]+dy) not in all_danger]
            if safe_cells:
                lines.append(f"    Safe moves: {' '.join(safe_cells)}")
            else:
                lines.append(f"    WARNING: No safe adjacent cell — move further!")
        else:
            lines.append(f"    Your position {my_pos} is safe.")
        # Flag any brick targets caught in this blast
        hit_bricks = [(bx, by) for bx, by in reachable_bricks if (bx, by) in blast_set]
        if hit_bricks:
            lines.append(f"    Bricks in blast (will score): {' '.join(f'({bx},{by})' for bx,by in hit_bricks)}")

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


def _build_active_threats(state: GameState, player_id: str) -> str:
    """Explicit per-bomb threat listing with tick-based timing and lethal zones."""
    if not state.bombs:
        return "  No active threats. All cells are safe."

    lines = []
    for b in state.bombs:
        owner_label = "Your bomb" if b.owner == player_id else "Enemy bomb"
        explodes_at_tick = state.tick + b.fuse_ticks
        safe_after_tick = explodes_at_tick + 5  # explosions last 5 ticks
        blast = compute_blast_cells(state.grid, b)
        lethal_str = " ".join(f"({c[0]},{c[1]})" for c in blast)
        lines.append(f"  {owner_label} at ({b.pos[0]},{b.pos[1]}): Explodes in {b.fuse_ticks} ticks (at tick {explodes_at_tick}).")
        lines.append(f"    Lethal Zones: {lethal_str}")
        lines.append(f"    Status: LETHAL when bomb detonates (until tick {safe_after_tick}). You CAN walk through these to escape, but do NOT stop or wait on them.")

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


def _build_own_bomb_warning(state: GameState, player_id: str) -> str:
    """Build a prominent warning banner when the player has an active bomb."""
    my_bombs = [b for b in state.bombs if b.owner == player_id]
    if not my_bombs:
        return ""

    lines = []
    for b in my_bombs:
        blast = compute_blast_cells(state.grid, b)
        lethal_str = " ".join(f"({c[0]},{c[1]})" for c in blast)
        explodes_at = state.tick + b.fuse_ticks
        lines.append(f"⚠ YOUR BOMB at ({b.pos[0]},{b.pos[1]}) explodes tick {explodes_at} ({b.fuse_ticks} ticks) — FORBIDDEN destinations: {lethal_str}")

    return "\n".join(lines)


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
    brick_targets_text = _build_brick_targets(state, player_id, reachable["bricks"], reachable_floor_set)
    bombs_text = _build_bombs_merged(state, player_id, reachable["bricks"], reachable_floor_set)
    score_text = score_situation(state, player_id)
    time_str = _format_time(state.time_remaining_ticks)

    own_bomb_warning = _build_own_bomb_warning(state, player_id)
    warning_line = f"\n{own_bomb_warning}" if own_bomb_warning else ""

    return f"""=== BOMBER-{player_id[-1]} | Tick {state.tick} ===
Score: YOU={me.score}  ENEMY={enemy.score}  |  Bricks: {state.bricks_remaining}  |  Time: {time_str}{warning_line}

MAP (15x13):
{ascii_grid}
Legend: # wall  b brick  . floor  1=you  2=enemy  *=your bomb  !=enemy bomb  X=explosion  x=blast shadow (passable but lethal on detonation)

BRICK TARGETS (bomb from adjacent tile, NOT from the brick itself):
{brick_targets_text}

BOMBS:
{bombs_text}

SCORE: {score_text}

Actions (respond with ONE JSON line):
  {{"reasoning":"...","action":"move","target":[x,y]}}
  {{"reasoning":"...","action":"move_and_bomb","target":[x,y]}}
  {{"reasoning":"...","action":"bomb_here"}}
  {{"reasoning":"...","action":"wait"}}
Rules: target must be a reachable "." tile; x tiles are passable but your final destination must be outside the blast zone; killing enemy = instant win."""
