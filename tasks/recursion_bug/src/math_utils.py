def factorial(n):
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
