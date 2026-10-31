"""雾城博弈的可运行教学模型，仅依赖 Python 标准库。

它帮助理解蓝图中的网格、DFS、BFS、迷雾和改墙事务；游戏运行仍以
Fogbound/Content 中保存的 Blueprint 为准。随机流按 UE 5.8 的整数
溢出和 float32 规则实现，并用 UE 导出的种子样本作交叉检查。
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import argparse
import json
import struct

WIDTH, HEIGHT = 21, 17
START, EXIT = 22, 334
DIRECTIONS = ((0, -1), (1, 0), (0, 1), (-1, 0))


def f32(value: float) -> float:
    """显式舍入到 float32，避免跨语言随机整数边界不一致。"""
    return struct.unpack('<f', struct.pack('<f', value))[0]


class UnrealStream:
    """UE 5.8 FRandomStream 的整数采样规则；不是密码学随机数。"""
    def __init__(self, seed: int):
        self.seed = seed & 0xffffffff

    def randint(self, low: int, high: int) -> int:
        self.seed = (self.seed * 196314165 + 907633515) & 0xffffffff
        # UE 5.8 使用高 23 位。旧版本或其他 RNG 不保证生成相同地图。
        fraction = (self.seed >> 9) / 8388608.0
        return low + int(f32(fraction * f32(high - low + 1)))


def next_cell(cell: int, direction: int, distance: int = 1) -> int:
    """先验证二维坐标，再生成一维索引，防止 20→21 跨行移动。"""
    dx, dy = DIRECTIONS[direction]
    x, y = cell % WIDTH + dx * distance, cell // WIDTH + dy * distance
    return y * WIDTH + x if 0 <= x < WIDTH and 0 <= y < HEIGHT else -1


def distance(a: int, b: int) -> int:
    return abs(a % WIDTH - b % WIDTH) + abs(a // WIDTH - b // WIDTH)


def find_path(walls: list[int], start: int, goal: int = EXIT) -> list[int]:
    """FIFO BFS。返回路径以便教学显示；蓝图 CheckPath 只返回布尔值。"""
    queue = deque([start])
    previous: dict[int, int | None] = {start: None}
    while queue:
        current = queue.popleft()
        if current == goal:
            path = []
            cursor: int | None = goal
            while cursor is not None:
                path.append(cursor)
                cursor = previous[cursor]
            return path[::-1]
        for direction in range(4):
            neighbour = next_cell(current, direction)
            if neighbour >= 0 and walls[neighbour] == 0 and neighbour not in previous:
                previous[neighbour] = current  # 入队时就标记，避免重复入队
                queue.append(neighbour)
    return []


@dataclass
class Maze:
    seed: int = 12345
    walls: list[int] = field(default_factory=lambda: [1] * (WIDTH * HEIGHT))
    supplies: list[int] = field(default_factory=lambda: [0] * (WIDTH * HEIGHT))
    explored: list[int] = field(default_factory=lambda: [0] * (WIDTH * HEIGHT))
    player: int = START
    elapsed: float = 0.0
    stamina: float = 100.0
    state: int = 0  # 0 准备，1 进行，2 A 胜，3 B 胜，4 暂停
    cooldown: float = 0.0
    edits: int = 0

    @classmethod
    def generate(cls, seed: int) -> Maze:
        maze = cls(seed=seed)
        rng = UnrealStream(seed)
        maze.walls[START] = 0
        stack = [START]
        while stack:
            current = stack[-1]
            candidates = []
            for direction in range(4):
                neighbour = next_cell(current, direction, 2)
                if neighbour >= 0 and 0 < neighbour % WIDTH < WIDTH - 1 and 0 < neighbour // WIDTH < HEIGHT - 1 and maze.walls[neighbour] == 1:
                    candidates.append(neighbour)
            if candidates:
                neighbour = candidates[rng.randint(0, len(candidates) - 1)]
                maze.walls[neighbour] = 0
                maze.walls[(current + neighbour) // 2] = 0
                stack.append(neighbour)
            else:
                stack.pop()  # DFS 回溯，不需要 Python 递归
        # UE ForLoop(0,45) 的末端包含在循环内，因此这里是 46 次尝试。
        for _ in range(46):
            # 当前蓝图的右侧乘法分支先求值，因此先消耗 Y 的随机数。
            # 相同随机公式还不够，复现随机调用顺序也很重要。
            y = rng.randint(1, 15)
            cell = rng.randint(1, 19) + WIDTH * y
            horizontal = maze.walls[cell - 1] == 0 and maze.walls[cell + 1] == 0
            vertical = maze.walls[cell - WIDTH] == 0 and maze.walls[cell + WIDTH] == 0
            if maze.walls[cell] == 1 and (horizontal or vertical):
                maze.walls[cell] = 0
        for _ in range(12):
            offset = rng.randint(0, WIDTH * HEIGHT - 1)
            for i in range(WIDTH * HEIGHT):
                cell = (i + offset) % (WIDTH * HEIGHT)
                if maze.walls[cell] == 0 and maze.supplies[cell] == 0 and cell != EXIT and distance(cell, START) >= 5:
                    maze.supplies[cell] = 1
                    break
        maze.reveal()
        maze.stamina = 100.0
        return maze

    @property
    def preview_radius(self) -> int:
        return 3 if self.elapsed >= 150 else 4 if self.elapsed >= 90 else 6

    def reveal(self) -> None:
        for cell in range(WIDTH * HEIGHT):
            if distance(cell, self.player) <= 2 and self.explored[cell] == 0:
                self.explored[cell] = 1
                if self.walls[cell] == 0:
                    self.stamina = min(100.0, self.stamina + .16)

    def visibility(self, cell: int, controller: bool) -> str:
        if self.explored[cell]:
            return 'known'
        if controller and distance(cell, self.player) <= self.preview_radius:
            return 'preview'
        return 'unknown'

    def edit(self, cell: int, erase_only: bool = False) -> tuple[bool, str]:
        """与 TryEdit 对应的事务：拒绝路径不合法的候选修改。"""
        if self.state != 1:
            return False, '对局未进行'
        if not 0 <= cell < WIDTH * HEIGHT:
            return False, '索引越界'
        if self.cooldown > 0:
            return False, '冷却中'
        if cell % WIDTH in (0, WIDTH - 1) or cell // WIDTH in (0, HEIGHT - 1):
            return False, '边界墙'
        if self.visibility(cell, True) == 'unknown':
            return False, '盲区'
        if cell in (START, EXIT) or distance(cell, self.player) <= 1 or self.supplies[cell]:
            return False, '保护格'
        old = self.walls[cell]
        if erase_only and old == 0:
            return False, '已经是通路'
        if self.elapsed >= 180 and old == 0:
            return False, '终局仅拆墙'
        self.walls[cell] = 1 - old
        if not find_path(self.walls, self.player):
            self.walls[cell] = old  # 回滚是算法的一部分，而不是 UI 提示
            return False, '必须保留通路'
        self.cooldown = 5.0 if self.elapsed >= 120 else 2.8
        self.edits += 1
        return True, '提交成功'

    def as_dict(self) -> dict:
        return {'seed': self.seed, 'width': WIDTH, 'height': HEIGHT, 'start': START, 'exit': EXIT,
                'walls': self.walls, 'supplies': self.supplies, 'explored': self.explored}

    def ascii(self, solution: bool = False) -> str:
        route = set(find_path(self.walls, self.player)) if solution else set()
        symbols = []
        for i, wall in enumerate(self.walls):
            symbols.append('A' if i == self.player else 'E' if i == EXIT else '#' if wall else '+' if self.supplies[i] else '.' if i in route else ' ')
        return '\n'.join(''.join(symbols[y * WIDTH:(y + 1) * WIDTH]) for y in range(HEIGHT))


def main() -> None:
    parser = argparse.ArgumentParser(description='Fogbound 网格算法教学模型')
    parser.add_argument('--seed', type=int, default=12345)
    parser.add_argument('--solution', action='store_true')
    parser.add_argument('--json', type=Path, help='将教学地图保存为 JSON')
    args = parser.parse_args()
    maze = Maze.generate(args.seed)
    print(maze.ascii(args.solution))
    print(f'种子 {args.seed}；最短路径 {len(find_path(maze.walls, START))-1} 步；补给 {sum(maze.supplies)} 个')
    if args.json:
        args.json.write_text(json.dumps(maze.as_dict(), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
