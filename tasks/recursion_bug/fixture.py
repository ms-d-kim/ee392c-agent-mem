"""Fixture reset for recursion_bug task.

Called by agent.run_vllm.reset_task_fixture() at the start of every run
to ensure the bug is freshly re-introduced.
"""

from pathlib import Path

BUGGY_SRC = '''def factorial(n):
    if n == 0:
        return 0  # bug: factorial(0) should be 1
    return n * factorial(n - 1)


def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


def power(base, exp):
    if exp == 0:
        return 1
    return base * power(base, exp - 1)
'''


def reset(task_dir: Path) -> None:
    src = task_dir / "src" / "math_utils.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(BUGGY_SRC)
