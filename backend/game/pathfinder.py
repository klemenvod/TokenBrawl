from collections import deque, defaultdict
from .state import Cell


def get_reachable(grid, start: list[int], bombs: list) -> dict:
    """
    BFS from start position.
    Returns dict with:
      - 'floor': list of reachable floor [x,y] positions
      - 'bricks': list of [x,y] brick positions adjacent to reachable floor
      - 'corridors': floor cells grouped by row and column for prompt readability
    Bombs are treated as passable (player walks through them).
    Only WALL and BRICK block movement.
    """
    H = len(grid)
    W = len(grid[0])
    sx, sy = start

    visited = set()
    visited.add((sx, sy))
    queue = deque([(sx, sy)])

    reachable_floor = []
    adjacent_bricks = set()

    while queue:
        x, y = queue.popleft()
        reachable_floor.append([x, y])

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in visited:
                cell = grid[ny][nx]
                if cell == Cell.WALL:
                    continue
                if cell == Cell.BRICK:
                    adjacent_bricks.add((nx, ny))
                    visited.add((nx, ny))
                    continue
                # FLOOR — passable
                visited.add((nx, ny))
                queue.append((nx, ny))

    # Group into corridors
    rows = defaultdict(list)
    cols = defaultdict(list)
    for x, y in reachable_floor:
        rows[y].append(x)
        cols[x].append(y)

    corridors = []

    # Horizontal corridors (rows)
    for y in sorted(rows.keys()):
        xs = sorted(rows[y])
        if len(xs) >= 2:
            # Split into contiguous segments
            segments = []
            seg = [xs[0]]
            for i in range(1, len(xs)):
                if xs[i] == seg[-1] + 1 or xs[i] == seg[-1] + 2:
                    seg.append(xs[i])
                else:
                    if len(seg) >= 2:
                        segments.append(seg)
                    seg = [xs[i]]
            if len(seg) >= 2:
                segments.append(seg)
            for seg in segments:
                cells = [[cx, y] for cx in seg]
                corridors.append({"type": "row", "index": y, "cells": cells})

    # Vertical corridors (columns)
    for x in sorted(cols.keys()):
        ys = sorted(cols[x])
        if len(ys) >= 2:
            segments = []
            seg = [ys[0]]
            for i in range(1, len(ys)):
                if ys[i] == seg[-1] + 1 or ys[i] == seg[-1] + 2:
                    seg.append(ys[i])
                else:
                    if len(seg) >= 2:
                        segments.append(seg)
                    seg = [ys[i]]
            if len(seg) >= 2:
                segments.append(seg)
            for seg in segments:
                cells = [[x, cy] for cy in seg]
                corridors.append({"type": "col", "index": x, "cells": cells})

    return {
        "floor": reachable_floor,
        "bricks": [[bx, by] for bx, by in sorted(adjacent_bricks)],
        "corridors": corridors,
    }


def find_path(grid, start: list[int], target: list[int], bombs: list) -> list[list[int]]:
    """
    BFS path from start to target.
    Returns list of [x,y] positions (not including start, including target).
    Returns empty list if no path exists.
    Walls and bricks block movement.
    If target is a BRICK, path goes to the cell adjacent to the brick
    (the last floor cell before it), not into the brick itself.
    """
    H = len(grid)
    W = len(grid[0])
    sx, sy = start
    tx, ty = target

    # Determine actual goal: if target is a brick, find adjacent floor cell closest to start
    target_is_brick = (0 <= ty < H and 0 <= tx < W and grid[ty][tx] == Cell.BRICK)

    if target_is_brick:
        # Find all floor cells adjacent to the brick
        adjacent_goals = []
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            ax, ay = tx + dx, ty + dy
            if 0 <= ax < W and 0 <= ay < H and grid[ay][ax] == Cell.FLOOR:
                adjacent_goals.append((ax, ay))
        if not adjacent_goals:
            return []
        goal_set = set(adjacent_goals)
    else:
        if grid[ty][tx] == Cell.WALL:
            return []
        goal_set = {(tx, ty)}

    # BFS
    visited = {}
    visited[(sx, sy)] = None
    queue = deque([(sx, sy)])

    found_goal = None
    while queue:
        x, y = queue.popleft()
        if (x, y) in goal_set and (x, y) != (sx, sy) or ((x, y) in goal_set and (sx, sy) in goal_set):
            found_goal = (x, y)
            break
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in visited:
                cell = grid[ny][nx]
                if cell == Cell.WALL or cell == Cell.BRICK:
                    # Allow if it's one of our goal cells (for non-brick targets on floor)
                    if (nx, ny) in goal_set and not target_is_brick:
                        visited[(nx, ny)] = (x, y)
                        found_goal = (nx, ny)
                        break
                    continue
                visited[(nx, ny)] = (x, y)
                queue.append((nx, ny))
        if found_goal:
            break

    # Handle case where start IS the goal
    if found_goal is None:
        if (sx, sy) in goal_set:
            return []  # Already at target
        return []  # No path

    # Reconstruct path
    path = []
    cur = found_goal
    while cur is not None and cur != (sx, sy):
        path.append([cur[0], cur[1]])
        cur = visited.get(cur)
    path.reverse()
    return path
