import asyncio
from collections import deque
from .state import GameState, Cell, Bomb, Explosion, Player
from .pathfinder import find_path


def compute_blast_cells(grid, bomb: Bomb) -> list[list[int]]:
    """
    Returns all cells hit by this bomb's explosion.
    Cross pattern: extends blast_radius cells in each of 4 directions.
    Stops at (and includes) first BRICK hit in each direction.
    Stops before (does not include) WALL cells.
    Always includes bomb's own cell.
    """
    H = len(grid)
    W = len(grid[0])
    bx, by = bomb.pos
    cells = [[bx, by]]

    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        for i in range(1, bomb.blast_radius + 1):
            nx, ny = bx + dx * i, by + dy * i
            if nx < 0 or nx >= W or ny < 0 or ny >= H:
                break
            cell = grid[ny][nx]
            if cell == Cell.WALL:
                break
            cells.append([nx, ny])
            if cell == Cell.BRICK:
                break  # Include the brick but stop extending

    return cells


async def tick(state: GameState) -> GameState:
    """
    One game tick (called every 100ms).
    """
    if state.game_over:
        return state

    # 1. Decrement all bomb fuses by 1
    for bomb in state.bombs:
        bomb.fuse_ticks -= 1

    # 2. Collect bombs where fuse_ticks <= 0 — use queue for chain reactions
    exploding_queue = deque()
    remaining_bombs = []
    for bomb in state.bombs:
        if bomb.fuse_ticks <= 0:
            exploding_queue.append(bomb)
        else:
            remaining_bombs.append(bomb)
    state.bombs = remaining_bombs

    # 3. Process explosions (with chain reactions)
    all_blast_cells = []
    exploded_bomb_positions = set()

    while exploding_queue:
        bomb = exploding_queue.popleft()
        bomb_key = (bomb.pos[0], bomb.pos[1])
        if bomb_key in exploded_bomb_positions:
            continue
        exploded_bomb_positions.add(bomb_key)

        blast_cells = compute_blast_cells(state.grid, bomb)
        all_blast_cells.extend(blast_cells)

        # a. Destroy bricks in blast cells, score to owner
        for bx, by in blast_cells:
            if state.grid[by][bx] == Cell.BRICK:
                state.grid[by][bx] = Cell.FLOOR
                state.players[bomb.owner].score += 1

        # b. Check if any other bomb is in blast cells -> chain reaction
        still_remaining = []
        for other_bomb in state.bombs:
            ob_key = (other_bomb.pos[0], other_bomb.pos[1])
            hit = False
            for bx, by in blast_cells:
                if ob_key == (bx, by):
                    hit = True
                    break
            if hit and ob_key not in exploded_bomb_positions:
                exploding_queue.append(other_bomb)
            else:
                still_remaining.append(other_bomb)
        state.bombs = still_remaining

        # c. Create Explosion object
        state.explosions.append(Explosion(cells=blast_cells, ttl_ticks=5))

    # Check player deaths after all explosions processed
    blast_set = set()
    for bx, by in all_blast_cells:
        blast_set.add((bx, by))

    for pid, player in state.players.items():
        if player.alive and tuple(player.pos) in blast_set:
            player.alive = False
            # Build death log: last actions leading to death
            state.death_log[pid] = {
                "killed_at": list(player.pos),
                "tick": state.tick,
                "last_actions": list(state.agent_action_history.get(pid, [])),
            }

    # 4. Decrement explosion TTLs, remove expired
    state.explosions = [e for e in state.explosions if e.ttl_ticks > 1]
    for e in state.explosions:
        e.ttl_ticks -= 1

    # 5. Decrement time
    state.time_remaining_ticks -= 1

    # 6. Update bricks remaining
    brick_count = 0
    for row in state.grid:
        for cell in row:
            if cell == Cell.BRICK:
                brick_count += 1
    state.bricks_remaining = brick_count

    # 7. Check win conditions
    p1 = state.players["p1"]
    p2 = state.players["p2"]

    if not p1.alive or not p2.alive:
        state.game_over = True
        if not p1.alive and not p2.alive:
            # Both dead simultaneously — higher score wins, or draw
            if p1.score > p2.score:
                state.winner = "p1"
            elif p2.score > p1.score:
                state.winner = "p2"
            else:
                state.winner = "draw"
        elif not p1.alive:
            state.winner = "p2"
        else:
            state.winner = "p1"
        state.win_reason = "kill"

    elif state.bricks_remaining == 0:
        state.game_over = True
        if p1.score > p2.score:
            state.winner = "p1"
        elif p2.score > p1.score:
            state.winner = "p2"
        else:
            state.winner = "draw"
        state.win_reason = "bricks"

    # Check majority win: a player has more than half the total bricks
    majority = state.total_bricks // 2 + 1
    if not state.game_over:
        if p1.score >= majority:
            state.game_over = True
            state.winner = "p1"
            state.win_reason = "majority"
        elif p2.score >= majority:
            state.game_over = True
            state.winner = "p2"
            state.win_reason = "majority"

    elif state.time_remaining_ticks <= 0:
        state.game_over = True
        if p1.score > p2.score:
            state.winner = "p1"
        elif p2.score > p1.score:
            state.winner = "p2"
        else:
            state.winner = "draw"
        state.win_reason = "timer"

    # 8. Increment tick
    state.tick += 1

    return state


def execute_move(state: GameState, player_id: str, path: list[list[int]], place_bomb: bool, movement_state: dict) -> None:
    """
    Called once per tick while the player is in motion.
    Moves player one step along path.
    When player reaches end of path, if place_bomb=True, place bomb at final position.
    """
    player = state.players[player_id]
    if not player.alive:
        return

    ms = movement_state.get(player_id)
    if ms is None:
        return

    # Move one step every 3 ticks
    ms["move_cooldown"] = ms.get("move_cooldown", 0) - 1
    if ms["move_cooldown"] > 0:
        return
    ms["move_cooldown"] = 3

    remaining_path = ms["path"]
    if not remaining_path:
        # Arrived at destination
        if ms["place_bomb"]:
            # Check max 1 bomb per player
            active_bombs = [b for b in state.bombs if b.owner == player_id]
            if len(active_bombs) == 0:
                state.bombs.append(Bomb(
                    pos=list(player.pos),
                    owner=player_id,
                    fuse_ticks=60,
                    blast_radius=player.blast_radius,
                ))
        # Clear movement
        movement_state[player_id] = None
        return

    # Move one step
    next_pos = remaining_path.pop(0)
    player.pos = next_pos
    ms["path"] = remaining_path

    # If path now empty and place_bomb, handle on next call
    if not remaining_path:
        if ms["place_bomb"]:
            active_bombs = [b for b in state.bombs if b.owner == player_id]
            if len(active_bombs) == 0:
                state.bombs.append(Bomb(
                    pos=list(player.pos),
                    owner=player_id,
                    fuse_ticks=60,
                    blast_radius=player.blast_radius,
                ))
        movement_state[player_id] = None


async def run_game_loop(state_ref: list, broadcast_fn, action_queues: dict, agents: dict = None):
    """
    Main loop. Runs until state.game_over = True.
    """
    # Movement state tracked outside GameState for serializability
    movement_state = {"p1": None, "p2": None}

    while not state_ref[0].game_over:
        state = state_ref[0]

        # 1. Check action queues for each player
        for pid in ["p1", "p2"]:
            if not state.players[pid].alive:
                continue

            # If player is not currently moving, check for new action
            if movement_state[pid] is None:
                try:
                    action = action_queues[pid].get_nowait()
                except asyncio.QueueEmpty:
                    continue

                action_type = action.get("action", "wait")
                target = action.get("target")
                reasoning = action.get("reasoning", "")

                # Store thoughts for broadcast
                state.agent_thoughts[pid] = reasoning
                state.agent_last_action[pid] = action_type

                # Track action history (keep last 5)
                state.agent_action_history[pid].append({
                    "tick": state.tick,
                    "pos": list(state.players[pid].pos),
                    "action": action_type,
                    "target": target,
                    "reasoning": reasoning,
                })
                if len(state.agent_action_history[pid]) > 5:
                    state.agent_action_history[pid].pop(0)

                if action_type == "wait":
                    continue

                if action_type == "bomb_here":
                    # Place bomb at current position immediately
                    active_bombs = [b for b in state.bombs if b.owner == pid]
                    if len(active_bombs) == 0:
                        state.bombs.append(Bomb(
                            pos=list(state.players[pid].pos),
                            owner=pid,
                            fuse_ticks=60,
                            blast_radius=state.players[pid].blast_radius,
                        ))
                    continue

                if target is None:
                    continue

                # Validate target
                if not isinstance(target, list) or len(target) != 2:
                    continue

                tx, ty = int(target[0]), int(target[1])
                place_bomb = action_type == "move_and_bomb"

                # Compute path
                path = find_path(state.grid, state.players[pid].pos, [tx, ty], state.bombs)
                if not path:
                    state.agent_thoughts[pid] = f"Invalid move: no path to ({tx},{ty}). Target must be a reachable floor tile."
                    state.agent_last_action[pid] = f"{action_type} (FAILED)"
                    continue

                movement_state[pid] = {
                    "path": path,
                    "place_bomb": place_bomb,
                }

        # 2. Advance movement for players currently moving
        for pid in ["p1", "p2"]:
            if movement_state[pid] is not None:
                execute_move(state, pid, movement_state[pid]["path"], movement_state[pid]["place_bomb"], movement_state)

        # 3. Tick
        state = await tick(state)
        state_ref[0] = state

        # 4. Copy agent thinking/moving state
        for pid in ["p1", "p2"]:
            state.agent_moving[pid] = movement_state[pid] is not None
        if agents:
            for pid in ["p1", "p2"]:
                state.agent_thinking[pid] = agents[pid].thinking

        # 5. Broadcast
        await broadcast_fn(state)

        # 6. Sleep
        await asyncio.sleep(0.1)
