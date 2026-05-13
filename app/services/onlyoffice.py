"""ONLYOFFICE editor helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
import time
from urllib.parse import quote
from urllib.request import Request, urlopen


OFFICE_EDITOR_EXTENSIONS: tuple[str, ...] = (
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".xlsm",
)


def is_onlyoffice_editable_extension(extension: str) -> bool:
    return extension.lower() in OFFICE_EDITOR_EXTENSIONS


def to_onlyoffice_document_type(extension: str) -> str:
    normalized = extension.lower()
    if normalized in {".doc", ".docx"}:
        return "word"
    if normalized in {".xls", ".xlsx", ".xlsm"}:
        return "cell"
    return "word"


def build_onlyoffice_document_key(file_path: Path) -> str:
    resolved = file_path.resolve()
    stat = resolved.stat()
    payload = f"{resolved}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()


def build_public_file_url(relative_path: str, public_backend_url: str) -> str:
    encoded = quote(relative_path, safe="")
    return f"{public_backend_url.rstrip('/')}/api/file?path={encoded}"


def build_callback_url(public_backend_url: str, path_token: str) -> str:
    encoded_token = quote(path_token, safe="")
    return f"{public_backend_url.rstrip('/')}/api/office/callback?path_token={encoded_token}"


def build_path_token(relative_path: str, secret: str, ttl_seconds: int) -> str:
    expires_at = int(time.time()) + max(300, int(ttl_seconds))
    payload = {"path": relative_path, "exp": expires_at}
    return encode_hs256_jwt(payload, secret)


def decode_path_token(token: str, secret: str) -> str | None:
    payload = decode_hs256_jwt(token, secret)
    if not payload:
        return None
    value = payload.get("path")
    if not isinstance(value, str) or not value:
        return None
    return value


def encode_hs256_jwt(payload: dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_segment = _b64url_encode(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header_segment}.{payload_segment}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_segment = _b64url_encode(signature)
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def decode_hs256_jwt(token: str, secret: str) -> dict | None:
    if not token or token.count(".") != 2:
        return None

    header_segment, payload_segment, signature_segment = token.split(".", 2)
    signing_input = f"{header_segment}.{payload_segment}".encode("utf-8")
    expected_signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        given_signature = _b64url_decode(signature_segment)
    except Exception:
        return None

    if not hmac.compare_digest(expected_signature, given_signature):
        return None

    try:
        payload_raw = _b64url_decode(payload_segment)
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        return None

    exp = payload.get("exp")
    if exp is not None:
        try:
            if int(exp) < int(time.time()):
                return None
        except Exception:
            return None
    return payload if isinstance(payload, dict) else None


def extract_bearer_token(header_value: str | None) -> str:
    if not header_value:
        return ""
    value = header_value.strip()
    if not value:
        return ""
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def callback_signing_secret(root_dir: Path, jwt_secret: str) -> str:
    if jwt_secret:
        return jwt_secret
    digest = hashlib.sha256(str(root_dir.resolve()).encode("utf-8", errors="ignore")).hexdigest()
    return f"local-fallback-{digest}"


def download_binary(url: str, timeout_seconds: int = 90) -> bytes:
    request = Request(url, method="GET")
    with urlopen(request, timeout=max(10, int(timeout_seconds))) as response:
        return response.read()


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))

