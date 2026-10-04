"""Mat geometry and named formations for nine toio cubes.

The mat is 7 columns by 5 rows. Column 1 is on the left, row 1 is at the top.
Adjacent cell centres are about 43 units apart, which satisfies the hub's
35-unit separation rule as long as every cube gets a distinct cell.
"""
import random

COLS, ROWS = 7, 5
X_MIN, X_MAX = 98.0, 402.0
Y_MIN, Y_MAX = 142.0, 358.0
CELL_W = (X_MAX - X_MIN) / COLS  # 304/7 ≈ 43.4
CELL_H = (Y_MAX - Y_MIN) / ROWS  # 216/5 = 43.2


def cell_center(col, row):
    """Return the (x, y) centre of a 1-based mat cell."""
    return (X_MIN + (col - 0.5) * CELL_W, Y_MIN + (row - 0.5) * CELL_H)


def _scatter(seed=20261004):
    cells = [(c, r) for r in range(1, ROWS + 1) for c in range(1, COLS + 1)]
    random.Random(seed).shuffle(cells)
    return cells[:9]


# Each value is nine distinct cells. Adjacent cells are allowed.
FORMATIONS = {
    "square": [(c, r) for r in (2, 3, 4) for c in (3, 4, 5)],
    # Ring around the centre cell, read clockwise from the top.
    "circle": [(4, 3), (4, 1), (6, 2), (7, 3), (6, 4), (4, 5), (2, 4), (1, 3), (2, 2)],
    # Two horizontal rows, centred on the mat.
    "line": [(c, 2) for c in range(2, 7)] + [(c, 4) for c in range(2, 6)],
    # Outline of a heart: two lobes, then a point.
    "heart": [(2, 1), (3, 1), (5, 1), (6, 1), (2, 2), (6, 2), (3, 3), (5, 3), (4, 4)],
    # Both diagonals through the centre. Nine unique cells.
    "x": [(2, 1), (6, 1), (3, 2), (5, 2), (4, 3), (3, 4), (5, 4), (2, 5), (6, 5)],
    "scatter": _scatter(),
    # Bottom row, plus the two cells just above the corners.
    "home": [(c, 5) for c in range(1, 8)] + [(1, 4), (7, 4)],
}


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def formation_centre(cells):
    xs, ys = zip(*(cell_center(c, r) for c, r in cells))
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _cube_id(cube, fallback):
    try:
        return int(cube.get("id", fallback))
    except (TypeError, ValueError):
        return cube.get("id", fallback)


def _cube_xy(cube):
    """Position in mat units, or None when the cube has not reported one."""
    if cube.get("x") is not None and cube.get("y") is not None:
        return (float(cube["x"]), float(cube["y"]))
    if cube.get("col") and cube.get("row"):
        return cell_center(int(cube["col"]), int(cube["row"]))
    return None


def _select_cells(cells, count):
    """Use every cell, or the `count` cells nearest the formation centre."""
    cells = list(cells)
    if count >= len(cells):
        return cells
    centre = formation_centre(cells)
    return sorted(cells, key=lambda cell: (_dist2(cell_center(*cell), centre), cell[0], cell[1]))[:count]


def _min_cost_assign(costs):
    """Exact assignment of workers to jobs. costs[worker][job] -> job index per worker.

    n and m stay tiny (at most 9), so a bit-mask DP is exact and cheap.
    """
    n = len(costs)
    if n == 0:
        return []
    m = len(costs[0])
    inf = float("inf")
    size = 1 << m
    dp = [[inf] * size for _ in range(n + 1)]
    parent = [[None] * size for _ in range(n + 1)]
    dp[0][0] = 0.0
    for k in range(n):
        for mask in range(size):
            base = dp[k][mask]
            if base == inf:
                continue
            for j in range(m):
                if mask & (1 << j):
                    continue
                nxt = mask | (1 << j)
                cost = base + costs[k][j]
                if cost < dp[k + 1][nxt]:
                    dp[k + 1][nxt] = cost
                    parent[k + 1][nxt] = (mask, j)
    best = min(range(size), key=lambda mask: dp[n][mask])
    choice = [None] * n
    mask = best
    for k in range(n, 0, -1):
        prev, job = parent[k][mask]
        choice[k - 1] = job
        mask = prev
    return choice


def _in_grid(col, row):
    return 1 <= col <= COLS and 1 <= row <= ROWS


def _front(col, row, heading):
    step = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}.get(heading)
    if step is None:
        return None
    nxt = (col + step[0], row + step[1])
    return nxt if _in_grid(*nxt) else None


def _nearest_free(origin, blocked):
    """In-grid cell not in `blocked`, nearest by centre, then smaller col, then row."""
    ox, oy = cell_center(*origin)
    best = None
    best_key = None
    for row in range(1, ROWS + 1):
        for col in range(1, COLS + 1):
            cand = (col, row)
            if cand in blocked:
                continue
            key = (_dist2(cell_center(col, row), (ox, oy)), col, row)
            if best_key is None or key < best_key:
                best_key = key
                best = cand
    return best


def clear_of_robot(cells, col, row, heading):
    """Formation cells that leave the robot's cell and the cell in front empty.

    Each blocked cell is replaced by the nearest free in-grid cell that is not
    already taken. The result stays the same length, with distinct cells.
    """
    blocked = {(int(col), int(row))}
    front = _front(int(col), int(row), heading)
    if front:
        blocked.add(front)
    used = set()
    out = []
    for cell in cells:
        cell = (int(cell[0]), int(cell[1]))
        if cell not in blocked and cell not in used:
            out.append(cell)
            used.add(cell)
            continue
        replacement = _nearest_free(cell, blocked | used)
        if replacement is None:
            out.append(cell)
            continue
        out.append(replacement)
        used.add(replacement)
    return out


def assign(cubes, cells):
    """Map connected cubes to distinct cells, minimising total travel.

    Cubes that have no position take the cells left over, in id order.
    When there are fewer cubes than cells, keep the cells nearest the centre.
    """
    connected = [c for c in cubes if c.get("connected", True)]
    connected.sort(key=lambda c: (_cube_id(c, 0),))
    if not connected:
        return {}
    chosen = _select_cells(cells, len(connected))
    known = []
    unknown = []
    for cube in connected:
        xy = _cube_xy(cube)
        (known if xy is not None else unknown).append((cube, xy))
    unknown.sort(key=lambda item: _cube_id(item[0], 0))
    if not known:
        ordered = sorted(connected, key=lambda c: _cube_id(c, 0))
        return {_cube_id(cube, i): chosen[i] for i, cube in enumerate(ordered)}

    centres = [cell_center(*cell) for cell in chosen]
    costs = [[_dist2(xy, centre) for centre in centres] for _, xy in known]
    jobs = _min_cost_assign(costs)
    mapping = {}
    used = set()
    for (cube, _), job in zip(known, jobs):
        mapping[_cube_id(cube, 0)] = chosen[job]
        used.add(job)
    rest = [cell for i, cell in enumerate(chosen) if i not in used]
    for (cube, _), cell in zip(unknown, rest):
        mapping[_cube_id(cube, 0)] = cell
    return mapping
