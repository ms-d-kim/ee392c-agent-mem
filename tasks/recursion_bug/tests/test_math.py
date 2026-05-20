from src.math_utils import factorial, fib, power


def test_factorial_base():
    assert factorial(0) == 1


def test_factorial_5():
    assert factorial(5) == 120


def test_factorial_recursive():
    assert factorial(6) == 720


def test_fib_small():
    assert fib(0) == 0
    assert fib(1) == 1


def test_fib_10():
    assert fib(10) == 55


def test_power_base():
    assert power(2, 0) == 1


def test_power_pos():
    assert power(3, 4) == 81
