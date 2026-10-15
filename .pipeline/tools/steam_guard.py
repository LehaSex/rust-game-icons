"""Steam Guard (maFile) handling.

A maFile is the full Steam Mobile Authenticator export. Holding one is
equivalent to holding the account password: it can generate login codes and
mobile confirmation keys. Treat it accordingly.

Invariants enforced by this module:

* the maFile is held in memory only and is never written to disk by us;
* it is never printed, logged, or embedded in an exception message;
* when it arrives as ``STEAM_MAFILE_B64`` it is decoded inside a single
  expression and the base64 form is dropped immediately;
* a maFile path inside the git work tree is rejected outright.

Source order: ``STEAM_MAFILE_B64`` -> ``STEAM_MAFILE`` -> ``--maFile``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV_B64 = "STEAM_MAFILE_B64"
ENV_PATH = "STEAM_MAFILE"

CHARSET = "23456789BCDFGHJKMNPQRTVWXY"
CODE_LEN = 5
WINDOW = 30

REQUIRED = ("shared_secret",)
KNOWN = {"account_name", "address", "cell_name", "cell_prefix", "device_identifier",
         "email", "facebook", "first_name", "google", "identity_secret", "is_remembered",
         "last_name", "ma_format", "mail_domain", "oauth_token", "proxy", "revocation_code",
         "serial_number", "server_time", "shared_secret", "status", "steam_id", "uri"}

TIME_URL = "https://api.steampowered.com/ITwoFactorService_QueryTime/v0001"


class GuardError(RuntimeError):
    """maFile is missing, malformed, or in an unsafe location. Message is safe to print."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def in_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(repo_root())
        return True
    except ValueError:
        return False


def _b64(value: object, field: str) -> bytes:
    if not isinstance(value, str):
        raise GuardError(f"maFile field '{field}' must be a string, got {type(value).__name__}")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GuardError(f"maFile field '{field}' is not valid base64 ({exc})") from None


def time_offset(url: str = TIME_URL, timeout: float = 5.0) -> int:
    """Offset of the local clock against Steam's, in seconds (RTT/2 compensated).

    Returns 0 when the probe fails; a wrong clock only matters if it is off by
    more than half the 30 s window.
    """
    started = time.time()
    try:
        with urllib.request.urlopen(f"{url}?msec=0", timeout=timeout) as resp:
            body = resp.read(4096).decode("ascii", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return 0
    remote = _remote_seconds(body)
    if remote is None:
        return 0
    return int(remote - (started + time.time()) / 2)


def _remote_seconds(body: str) -> float | None:
    try:
        payload = json.loads(body)["response"]
        return float(payload["server_time"]) + float(payload.get("server_time_buffer", 0))
    except (ValueError, KeyError, TypeError):
        return None


def twofactor_code(shared_secret: bytes, timestamp: int) -> str:
    """Steam's 2FA code for a timestamp.

    Same construction as SteamRE/python-steam `generate_twofactor_code_for_time`:
    HMAC-SHA1 over `timestamp // 30` as a big-endian 64-bit integer, a dynamic
    4-byte window picked from the digest, then five characters drawn from
    Steam's 26-character alphabet.
    """
    digest = hmac.new(shared_secret, struct.pack(">Q", int(timestamp) // WINDOW), hashlib.sha1).digest()
    start = digest[19] & 0xF
    value = struct.unpack(">I", digest[start:start + 4])[0] & 0x7FFFFFFF
    code = ""
    for _ in range(CODE_LEN):
        value, index = divmod(value, len(CHARSET))
        code += CHARSET[index]
    return code


def codes(secrets: dict, count: int = 3, offset: int | None = None) -> list[str]:
    """The next `count` consecutive codes, so a retry cannot reuse a spent one."""
    if count < 1:
        raise GuardError("code count must be at least 1")
    shared = _b64(secrets["shared_secret"], "shared_secret")
    now = int(time.time()) + (time_offset() if offset is None else offset)
    return [twofactor_code(shared, now + i * WINDOW) for i in range(count)]


def validate(data: object) -> dict:
    if not isinstance(data, dict):
        raise GuardError("maFile must be a JSON object")
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise GuardError(f"maFile is missing required field(s): {', '.join(missing)}")
    _b64(data["shared_secret"], "shared_secret")
    if data.get("identity_secret"):
        _b64(data["identity_secret"], "identity_secret")
    return data


def describe(data: dict) -> str:
    """A safe one-line summary: enough to confirm which account, no secret material."""
    name = data.get("account_name") or "?"
    serial = data.get("serial_number") or "?"
    fingerprint = _b64(data["shared_secret"], "shared_secret")
    tag = hashlib.sha256(fingerprint).hexdigest()[:8]
    return f"account={name} serial={serial} shared_secret=sha256:{tag}"


def load(explicit: str | Path | None = None, env: dict | None = None) -> dict:
    """Resolve the maFile from base64, then env path, then the explicit argument."""
    env = os.environ if env is None else env

    if env.get(ENV_B64):
        raw = env[ENV_B64].strip().replace("\n", "")
        try:
            decoded = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise GuardError(f"{ENV_B64} is not valid base64 ({exc})") from None
        del raw
        try:
            data = json.loads(decoded)
        except (ValueError, UnicodeDecodeError) as exc:
            raise GuardError(f"{ENV_B64} did not decode to JSON ({exc})") from None
        del decoded
        return validate(data)

    path = explicit or env.get(ENV_PATH)
    if not path:
        raise GuardError(
            f"no maFile given: set {ENV_B64} (base64), {ENV_PATH}, or pass --maFile"
        )
    path = Path(path).expanduser()
    if in_repo(path):
        raise GuardError(
            f"refusing to read a maFile from inside the repository: {path}. "
            "Move it outside the work tree - it must never be committed."
        )
    if not path.is_file():
        raise GuardError(f"maFile not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise GuardError(f"maFile at {path} does not parse ({exc})") from None
    if in_repo(path) or str(path).startswith(str(repo_root())):
        raise GuardError("maFile must live outside the repository")
    return validate(data)


def redact(text: str, needles: tuple[str, ...] = ()) -> str:
    """Defence in depth: strip secret material from anything about to be logged."""
    for needle in needles:
        if needle:
            text = text.replace(needle, "********")
    return text


def warn_unknown(data: dict) -> list[str]:
    return sorted(k for k in data if k not in KNOWN)


if __name__ == "__main__":
    try:
        loaded = load()
    except GuardError as err:
        raise SystemExit(f"maFile error: {err}")
    print(describe(loaded))
    extra = warn_unknown(loaded)
    if extra:
        print(f"note: {len(extra)} unrecognised field(s) ignored: {', '.join(extra)}")
    drift = abs(int(time.time()) - int(loaded.get("server_time", 0)))
    if loaded.get("server_time") and drift > 300:
        print(f"warning: maFile server_time is {drift}s away from this machine")