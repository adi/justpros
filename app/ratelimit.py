import time
from collections import defaultdict
from functools import wraps

from fastapi import HTTPException, Request, status

# Store: {key: [timestamp, ...]}
_requests: dict[str, list[float]] = defaultdict(list)

# Store: {ip: (block_until_timestamp, violation_count)}
_blocked_ips: dict[str, tuple[float, int]] = {}

# Block settings
BLOCK_DURATION_SECONDS = 3600  # 1 hour
VIOLATIONS_BEFORE_BLOCK = 3  # Block after 3 rate limit hits


def _clean_old_requests(key: str, window_seconds: int) -> None:
    """Remove requests older than the window."""
    cutoff = time.time() - window_seconds
    _requests[key] = [t for t in _requests[key] if t > cutoff]


def _get_client_ip(request: Request) -> str:
    """Get client IP, respecting CF-Connecting-IP header."""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_ip_blocked(ip: str) -> bool:
    """Check if IP is currently blocked."""
    if ip not in _blocked_ips:
        return False
    block_until, _ = _blocked_ips[ip]
    if time.time() > block_until:
        del _blocked_ips[ip]
        return False
    return True


def _record_violation(ip: str) -> None:
    """Record a rate limit violation and block if threshold exceeded."""
    now = time.time()
    if ip in _blocked_ips:
        _, count = _blocked_ips[ip]
        count += 1
    else:
        count = 1

    if count >= VIOLATIONS_BEFORE_BLOCK:
        _blocked_ips[ip] = (now + BLOCK_DURATION_SECONDS, count)
    else:
        # Keep track of violations without blocking yet
        _blocked_ips[ip] = (now + 300, count)  # Reset count after 5 min of good behavior


def rate_limit(max_requests: int, window_seconds: int):
    """
    Rate limit decorator for FastAPI endpoints.

    Usage:
        @router.post("/login")
        @rate_limit(max_requests=10, window_seconds=60)
        async def login(request: Request, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Request = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if not request:
                return await func(*args, **kwargs)

            ip = _get_client_ip(request)

            # Check if IP is blocked
            if _is_ip_blocked(ip):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. You are temporarily blocked. Try again in 1 hour.",
                )

            key = f"{func.__name__}:{ip}"
            _clean_old_requests(key, window_seconds)

            if len(_requests[key]) >= max_requests:
                _record_violation(ip)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please try again later.",
                )

            _requests[key].append(time.time())
            return await func(*args, **kwargs)

        return wrapper
    return decorator
