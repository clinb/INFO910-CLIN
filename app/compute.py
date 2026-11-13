from math import isqrt


MAX_N = 10_000_000


def count_primes(n: int) -> int:
    if not 0 <= n <= MAX_N:
        raise ValueError(f"n must be between 0 and {MAX_N}")
    if n < 2:
        return 0
    sieve = bytearray(b"\x01") * (n + 1)
    sieve[0:2] = b"\x00\x00"
    for prime in range(2, isqrt(n) + 1):
        if sieve[prime]:
            start = prime * prime
            sieve[start::prime] = b"\x00" * ((n - start) // prime + 1)
    return sieve.count(1)
