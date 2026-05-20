import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))
from math_utils import add, multiply

def test_add():
    assert add(2, 3) == 5
    assert add(0, 0) == 0

def test_multiply():
    assert multiply(2, 3) == 6
