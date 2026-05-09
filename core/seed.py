"""Global seed management for reproducibility.

Set ALL randomness sources from one call. Required by validation pipeline.
"""
from __future__ import annotations
import hashlib
import os
import random
import numpy as np

GLOBAL_SEED: int | None = None


def set_global_seed(seed: int) -> None:
    """Set seed across python, numpy, torch (if installed), env.

    Should be called ONCE at start of any reproducible run.

    Notes:
        Numba JIT-compiled code that consumes randomness via ``np.random.*``
        shares the global numpy RNG. ``np.random.seed(seed)`` therefore also
        seeds numba JIT RNGs that delegate to numpy. If a JIT path uses
        numba's own ``random`` module (rare; available in some numba
        versions), we attempt to call its ``seed()`` defensively. Both
        branches are no-ops when numba is missing.
    """
    global GLOBAL_SEED
    GLOBAL_SEED = int(seed)
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import torch
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass
    # Numba: most JIT RNG paths route through numpy's global RNG, which
    # we already seeded above. Some numba versions also expose a separate
    # numba.random module with its own seed(); call defensively if present.
    try:
        import numba
        nb_random = getattr(numba, "random", None)
        if nb_random is not None and hasattr(nb_random, "seed"):
            nb_random.seed(int(seed))  # pragma: no cover - version dependent
    except ImportError:
        pass


def get_seed() -> int | None:
    return GLOBAL_SEED


def child_rng(name: str) -> np.random.Generator:
    """Spawn deterministic child RNG from global seed + name.

    Use for sub-components that need own randomness without polluting global state.

    Implementation note: uses SHA-256 of "{GLOBAL_SEED}:{name}" rather than
    Python's built-in ``hash()`` because the latter is randomized per process
    via PYTHONHASHSEED, which makes child RNGs non-reproducible across
    independent worker processes (e.g. multiprocessing). SHA-256 gives the
    same 32-bit derived seed for the same (GLOBAL_SEED, name) pair regardless
    of process.
    """
    if GLOBAL_SEED is None:
        raise RuntimeError("Global seed not set. Call set_global_seed(N) first.")
    digest = hashlib.sha256(f"{GLOBAL_SEED}:{name}".encode()).digest()
    h = int.from_bytes(digest[:4], "big")
    return np.random.default_rng(h)
