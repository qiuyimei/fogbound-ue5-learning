"""运行：python -m unittest discover -s Reference -v"""
import unittest
import json
from pathlib import Path
from maze_reference import Maze, WIDTH, HEIGHT, START, EXIT, next_cell, find_path, distance


class ReferenceTests(unittest.TestCase):
    def test_all_seed_samples_match_unreal(self):
        samples = json.loads((Path(__file__).parents[1]/'Learning/Data/ue_seed_samples.json').read_text(encoding='utf-8'))
        for sample in samples:
            with self.subTest(seed=sample['seed']):
                actual = Maze.generate(sample['seed'])
                self.assertEqual(sample['walls'], actual.walls)
                self.assertEqual(sample['supplies'], actual.supplies)
                self.assertEqual(sample['explored'], actual.explored)

    def test_many_maps_are_solvable(self):
        for seed in range(1, 101):
            maze = Maze.generate(seed)
            self.assertTrue(find_path(maze.walls, START), seed)
            self.assertEqual(sum(maze.supplies), 12)
            self.assertTrue(all(maze.walls[i] == 0 for i, supply in enumerate(maze.supplies) if supply))

    def test_row_wrap_is_rejected(self):
        self.assertEqual(next_cell(20, 1), -1)
        self.assertEqual(next_cell(21, 3), -1)
        self.assertEqual(next_cell(0, 0), -1)

    def test_preview_does_not_reveal_items(self):
        maze = Maze.generate(42)
        for cell in range(WIDTH*HEIGHT):
            if maze.visibility(cell, True) == 'preview':
                self.assertEqual(maze.visibility(cell, False), 'unknown')
        self.assertEqual(maze.visibility(START, False), 'known')

    def test_unique_path_block_rolls_back(self):
        maze = Maze.generate(1)
        maze.walls = [1] * (WIDTH * HEIGHT)
        for x in range(1,20): maze.walls[21+x] = 0
        for y in range(1,16): maze.walls[y*21+19] = 0
        maze.supplies = [0] * (WIDTH*HEIGHT)
        maze.explored = [1] * (WIDTH*HEIGHT)
        maze.state = 1
        original = maze.walls.copy()
        accepted, reason = maze.edit(28)
        self.assertFalse(accepted)
        self.assertEqual(reason, '必须保留通路')
        self.assertEqual(maze.walls, original)
        self.assertEqual(maze.cooldown, 0)
        self.assertEqual(maze.edits, 0)

    def test_exhaustive_edits_preserve_reachability(self):
        maze = Maze.generate(271828)
        maze.explored = [1] * (WIDTH*HEIGHT)
        maze.state = 1
        for cell in range(WIDTH*HEIGHT):
            maze.cooldown = 0
            original = maze.walls.copy()
            accepted, _ = maze.edit(cell)
            if accepted:self.assertTrue(find_path(maze.walls, maze.player))
            else:self.assertEqual(maze.walls, original)

    def test_preview_decay(self):
        maze=Maze.generate(1)
        for elapsed,radius in [(0,6),(90,4),(150,3)]:
            maze.elapsed=elapsed;self.assertEqual(maze.preview_radius,radius)


if __name__=='__main__':unittest.main()
