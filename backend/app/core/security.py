import hashlib
import hmac

from app.core.config import get_settings


def make_token(user_id: int) -> str:
    """Simple signed token for MVP (no expiry). Replace with JWT + refresh
    in production."""
    secret = get_settings().secret_key.encode()
    sig = hmac.new(secret, str(user_id).encode(), hashlib.sha256).hexdigest()[:16]
    return f"{user_id}.{sig}"


def parse_token(token: str) -> int | None:
    try:
        user_id_s, sig = token.split(".", 1)
        user_id = int(user_id_s)
    except ValueError:
        return None
    if hmac.compare_digest(make_token(user_id), token):
        return user_id
    return None
