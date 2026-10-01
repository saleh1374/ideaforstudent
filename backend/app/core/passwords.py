"""MVP password hashing (stdlib only; swap for passlib/argon2 in production)."""
import hashlib
import hmac as hmac_mod


def hash_password(password: str, salt: str = "daneshyar") -> str:
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hmac_mod.compare_digest(hash_password(password), hashed)
