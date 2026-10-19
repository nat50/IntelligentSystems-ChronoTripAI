"""Optional Numba acceleration.

The solver runs unchanged without Numba (pure Python), just slower. With Numba
installed the scheduling kernel is compiled once and cached on disk.
"""

try:  # pragma: no cover - import guard
    from numba import njit

    HAS_NUMBA = True
except Exception:  # pragma: no cover
    HAS_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore[no-redef]
        if args and callable(args[0]):
            return args[0]

        def deco(fn):
            return fn

        return deco
