"""Accounts and sessions for the web console.

Passwords are stored only as salted scrypt hashes (stdlib `hashlib.scrypt`). Two files hold
accounts: the committed `configs/users.yaml` (the public demo account) and the local
`<runs_dir>/_workspace/users.yaml` that `consenttrace user add` writes to. Sessions are random
tokens kept in this process's memory, so restarting the server signs everyone out.

The demo account is public on purpose: `demo_login` in configs/users.yaml is what the login
page offers as "演示账号一键进入". It still logs in through the same password check.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
SESSION_TTL = 12 * 3600
LOCAL_USERS_FILE = Path("_workspace") / "users.yaml"


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b64 = base64.b64encode
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    password_hash: str

    def public(self) -> dict[str, str]:
        return {"username": self.username, "display_name": self.display_name}


class UserStore:
    """Accounts read from one or more YAML files; later files may add users, never replace one."""

    def __init__(self, *paths: Path) -> None:
        self.paths = [Path(p) for p in paths]

    def _read(self) -> tuple[dict[str, User], dict[str, str] | None]:
        users: dict[str, User] = {}
        demo = None
        for path in self.paths:
            if not path.exists():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for name, row in (data.get("users") or {}).items():
                if name not in users and isinstance(row, dict) and row.get("password_hash"):
                    users[name] = User(str(name), str(row.get("display_name") or name), str(row["password_hash"]))
            if demo is None and isinstance(data.get("demo_login"), dict):
                demo = {"username": str(data["demo_login"]["username"]), "password": str(data["demo_login"]["password"])}
        return users, demo

    def users(self) -> dict[str, User]:
        return self._read()[0]

    def demo_login(self) -> dict[str, str] | None:
        users, demo = self._read()
        return demo if demo and demo["username"] in users else None

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.users().get(username.strip())
        # hash even for an unknown name, so the response time does not reveal which names exist
        ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
        return user if user and ok else None


_DUMMY_HASH = hash_password("not-a-real-account", salt=b"\0" * 16)


def add_user(path: Path, username: str, password: str, display_name: str | None = None) -> None:
    """Add or replace one account in a users file (used by `consenttrace user add`)."""
    if not username or any(c.isspace() for c in username):
        raise ValueError("用户名不能为空，也不能含空白字符")
    if len(password) < 8:
        raise ValueError("密码至少 8 位")
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    users = data.setdefault("users", {})
    users[username] = {"display_name": display_name or username, "password_hash": hash_password(password)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Local console accounts (consenttrace user add). Passwords are scrypt hashes.\n"
        + yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


class Sessions:
    def __init__(self, ttl: float = SESSION_TTL) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._by_token: dict[str, tuple[str, float]] = {}

    def create(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._by_token[token] = (username, time.time() + self.ttl)
        return token

    def get(self, token: str | None) -> str | None:
        if not token:
            return None
        with self._lock:
            found = self._by_token.get(token)
            if found is None:
                return None
            username, expires = found
            if expires < time.time():
                del self._by_token[token]
                return None
            return username

    def drop(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._by_token.pop(token, None)
