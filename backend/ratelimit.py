import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException

from models import User
from security import get_current_user

_hits: dict[tuple[str, int], deque] = defaultdict(deque)


def reset() -> None:
    _hits.clear()


def rate_limit(name: str, max_calls: int, per_seconds: int):
    """Dependency: allow `max_calls` per user per `per_seconds`. Returns the user."""

    async def dependency(user: User = Depends(get_current_user)) -> User:
        now = time.monotonic()
        window = _hits[(name, user.id)]
        while window and now - window[0] > per_seconds:
            window.popleft()
        if len(window) >= max_calls:
            raise HTTPException(429, f"Too many {name} requests. Try again in a minute.")
        window.append(now)
        return user

    return dependency
