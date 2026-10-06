"""Run: python src/input_handler/test/test_quadrature.py  (also works under pytest)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'input_handler'))
from quadrature import Quadrature  # noqa: E402

CW = [(0, 1), (1, 1), (1, 0), (0, 0)]
CCW = [(1, 0), (1, 1), (0, 1), (0, 0)]


def _run(seq, q):
    return [q.update(a, b) for a, b in seq]


def test_one_detent_each_way():
    assert sum(_run(CW, Quadrature(0, 0))) == 1
    assert sum(_run(CCW, Quadrature(0, 0))) == -1


def test_bounce_does_not_count():
    q = Quadrature(0, 0)
    # wiggle 00 <-> 01 many times, then settle back on 00: net zero detents
    assert sum(_run([(0, 1), (0, 0)] * 20, q)) == 0
    # a skipped state (00 -> 11) is invalid and ignored
    assert q.update(1, 1) == 0


def test_three_detents():
    assert sum(_run(CW * 3, Quadrature(0, 0))) == 3


if __name__ == '__main__':
    test_one_detent_each_way()
    test_bounce_does_not_count()
    test_three_detents()
    print('quadrature ok')
