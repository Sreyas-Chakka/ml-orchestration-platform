"""JWT authentication + role-based access control.

Two token types share one signing key:
  * user tokens  (typ=user) — issued at login, carry the user's role.
  * run tokens   (typ=run)  — minted per run and injected into the training container, so a
    pod can only report metrics/artifacts for *its own* run and nothing else.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Role, User

ROLE_RANK = {Role.viewer: 0, Role.researcher: 1, Role.admin: 2}
bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def _encode(payload: dict, ttl: timedelta) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    return jwt.encode({**payload, "iat": now, "exp": now + ttl}, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_access_token(user: User) -> str:
    s = get_settings()
    return _encode(
        {"sub": str(user.id), "role": user.role.value, "typ": "user"},
        timedelta(minutes=s.access_token_minutes),
    )


def create_run_token(run_id: int) -> str:
    return _encode({"sub": f"run:{run_id}", "run_id": run_id, "typ": "run"}, timedelta(hours=get_settings().run_token_hours))


def decode_token(token: str) -> dict:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


def _claims(creds: HTTPAuthorizationCredentials | None) -> dict:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    return decode_token(creds.credentials)


def current_user(creds=Depends(bearer), db: Session = Depends(get_db)) -> User:
    claims = _claims(creds)
    if claims.get("typ") != "user":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User token required")
    user = db.get(User, int(claims["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


def require_role(minimum: Role):
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{minimum.value}' or higher")
        return user

    return dep


def run_identity(run_id: int, creds=Depends(bearer)) -> int:
    """Authorize a training pod: its run token must match the run in the URL."""
    claims = _claims(creds)
    if claims.get("typ") != "run" or claims.get("run_id") != run_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Run token does not match this run")
    return run_id


def ensure_bootstrap_users(db: Session) -> None:
    s = get_settings()
    if db.query(User).count() > 0:
        return
    users = [(s.bootstrap_admin_email, "Platform Admin", s.bootstrap_admin_password, Role.admin)]
    if s.seed_demo_users:
        users += [
            ("researcher@mlops.local", "Demo Researcher", "research123", Role.researcher),
            ("viewer@mlops.local", "Demo Viewer", "viewer123", Role.viewer),
        ]
    for email, name, pw, role in users:
        db.add(User(email=email, name=name, password_hash=hash_password(pw), role=role))
    db.commit()
