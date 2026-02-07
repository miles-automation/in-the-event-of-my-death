#!/usr/bin/env python3
"""
Smoke test for IEOMD staging/production deployments.

This script is intentionally a deploy guardrail:
- Fast (<~3m typical)
- Deterministic where possible
- Actionable failures (step name, HTTP status/body preview)

Flow (default):
1. Health check
2. Feedback endpoint (optional via --test-feedback; off by default)
3. Web serving + asset load (optional via --skip-web)
4. Attachment upload (if cryptography installed + object storage enabled)
5. Secret creation (PoW + POST /secrets, with attachment if uploaded)
6. Edit-token status check
7. Edit flow (PUT /secrets/edit + re-check status)
8. Decrypt-token status check
9. Public status-by-id check
10. Retrieve pending check (optional; only when unlock is soon)
11. Unlock + retrieve + attachment download + one-time delete (optional)
12. Capability token flow (optional via --capability-token-key)

Usage:
    ./scripts/smoke-test.py https://staging.example.com
    ./scripts/smoke-test.py https://staging.example.com --health-only
"""

import argparse
import base64
import hashlib
import json
import random
import re
import secrets
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

# Optional: cryptography for attachment encryption tests
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

SkipCheck = Callable[["SmokeContext"], str | None]


class ApiError(RuntimeError):
    def __init__(self, status_code: int, body: str):
        super().__init__(f"API error {status_code}: {body}")
        self.status_code = status_code
        self.body = body


# Keep unlock close enough to exercise unlock/retrieve lifecycle without making
# the smoke test slow. Environments may enforce a higher min unlock; we detect
# and adapt (see compute_unlock_at_for_environment()).
DEFAULT_UNLOCK_SECONDS = 90
EXPIRY_GAP_MINUTES = 65
MIN_UNLOCK_BUFFER_SECONDS = 5
# Threshold used to decide whether to wait/poll for unlock-related behaviors.
UNLOCK_SOON_MAX_SECONDS = 120
UNLOCK_POLL_DEADLINE_SECONDS = 120
UNLOCK_POLL_SLEEP_SECONDS = 2
EDIT_POSTPONE_SECONDS = 15
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.5
# Used when surfacing API error bodies (text) for debugging without log spam.
MAX_ERROR_BODY_CHARS = 10_000
# Used when surfacing raw HTTP bodies (bytes) as a preview in error messages.
BODY_PREVIEW_BYTES = 200
MAX_BACKOFF_SECONDS = 4.0


def log(msg: str) -> None:
    """Print timestamped log message."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _preview_bytes(value: bytes, limit: int = BODY_PREVIEW_BYTES) -> bytes:
    if len(value) <= limit:
        return value
    return value[:limit]


def _decode_limited(value: bytes, max_chars: int = MAX_ERROR_BODY_CHARS) -> str:
    decoded = value.decode("utf-8", errors="replace")
    if len(decoded) <= max_chars:
        return decoded
    return decoded[:max_chars] + "…"


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 425, 429, 502, 503, 504, 522, 524}


@dataclass
class HttpClient:
    base_url: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    retries: int = DEFAULT_RETRIES
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        effective_timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        req_headers = headers or {}

        last_error: Exception | None = None
        max_attempts = max(1, self.retries + 1)
        for attempt in range(1, max_attempts + 1):
            try:
                request = Request(url, data=body, headers=req_headers, method=method)
                try:
                    with urlopen(request, timeout=effective_timeout) as response:
                        return response.getcode(), dict(response.headers.items()), response.read()
                except HTTPError as e:
                    error_body = e.read() if e.fp else b""
                    resp_headers = dict(e.headers.items()) if e.headers else {}
                    if attempt < max_attempts and _is_retryable_status(e.code):
                        last_error = e
                        self._sleep_backoff(attempt)
                        continue
                    return e.code, resp_headers, error_body
            except (URLError, TimeoutError) as e:
                last_error = e
                if attempt < max_attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise RuntimeError(f"Network error after {attempt} attempts: {e}") from e

        # Defensive safety net: loop should always return or raise above.
        raise RuntimeError(f"Unexpected HTTP client failure: {last_error!r}")

    def api_json(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/api/v1{path}"
        req_headers: dict[str, str] = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)

        body_bytes = json.dumps(data).encode() if data is not None else None
        status, _, body = self.request(
            method,
            url,
            headers=req_headers,
            body=body_bytes,
            timeout_seconds=timeout_seconds,
        )
        if status < 200 or status >= 300:
            raise ApiError(status, _decode_limited(body))
        try:
            return json.loads(body.decode())
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Invalid JSON response from {method} {path}: preview={_preview_bytes(body)!r}"
            ) from e

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        return self.request(
            "GET",
            url,
            headers=headers,
            timeout_seconds=timeout_seconds,
        )

    def _sleep_backoff(self, attempt: int) -> None:
        base = self.retry_backoff_seconds * (2 ** (attempt - 1))
        jitter = random.random() * self.retry_backoff_seconds
        time.sleep(min(MAX_BACKOFF_SECONDS, base + jitter))


def parse_utc_datetime(value: str) -> datetime:
    """
    Parse an API UTC datetime string.

    Backend responses are expected to be ISO-like with a trailing "Z"
    (e.g., "2025-01-01T12:34:56Z").
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"Invalid datetime value: {value!r}")

    if value.endswith("Z"):
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_utc_datetime(dt: datetime) -> str:
    dt_utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt_utc.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_timestamps_match(
    label: str,
    expected_unlock_at: datetime,
    expected_expires_at: datetime,
    actual_unlock_at: datetime,
    actual_expires_at: datetime,
) -> bool:
    if actual_unlock_at != expected_unlock_at or actual_expires_at != expected_expires_at:
        log(
            f"ERROR: {label}: expected=({expected_unlock_at.isoformat()}, {expected_expires_at.isoformat()}) "
            f"actual=({actual_unlock_at.isoformat()}, {actual_expires_at.isoformat()})"
        )
        return False
    return True


def compute_unlock_at_for_environment(api_error: ApiError) -> datetime | None:
    """
    If the API rejected unlock_at due to environment min unlock policy, return an adjusted unlock_at.
    """
    if api_error.status_code not in (400, 422):
        return None

    m = re.search(r"Unlock date must be at least (\\d+) minutes in the future", api_error.body)
    if not m:
        return None

    min_minutes = int(m.group(1))
    now = datetime.now(timezone.utc)
    return now + timedelta(minutes=min_minutes, seconds=MIN_UNLOCK_BUFFER_SECONDS)


class _HTMLAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.asset_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: v for k, v in attrs if v is not None}

        if tag == "script":
            src = attrs_dict.get("src")
            if src:
                self.asset_urls.append(src)

        if tag == "link":
            rel = (attrs_dict.get("rel") or "").lower()
            href = attrs_dict.get("href")
            if not href:
                return
            if any(token in rel for token in ("stylesheet", "modulepreload", "preload")):
                self.asset_urls.append(href)


def check_web_serving(client: HttpClient) -> None:
    """
    Verify the web frontend is being served.

    - GET / returns 200 and looks like HTML
    - At least one referenced same-origin asset (script/css) loads (200)
    """
    homepage_url = f"{client.base_url}/"
    log(f"Checking web homepage: {homepage_url}")
    status, resp_headers, body = client.get(homepage_url, timeout_seconds=20.0)
    content_type_header = next(
        (v for k, v in resp_headers.items() if k.lower() == "content-type"),
        "",
    )
    if status != 200:
        raise RuntimeError(
            f"Homepage returned non-200: {status} "
            f"(content_type={content_type_header!r}, body_preview={_preview_bytes(body)!r})"
        )

    content_type = content_type_header.lower()
    if "text/html" not in content_type:
        raise RuntimeError(f"Homepage Content-Type not HTML: {content_type!r}")

    if not body:
        raise RuntimeError("Homepage returned empty body")

    body_text = body.decode("utf-8", errors="replace")
    if 'id="root"' not in body_text and "id='root'" not in body_text:
        if len(body) < 200:
            raise RuntimeError(
                "Homepage HTML missing expected root marker and is unexpectedly small "
                f"({len(body)} bytes, preview={_preview_bytes(body)!r})"
            )
        log('WARNING: Homepage HTML missing expected root marker (id="root"); continuing')

    parser = _HTMLAssetParser()
    parser.feed(body_text)

    base_parsed = urlparse(client.base_url)
    base_netloc = base_parsed.netloc
    if not base_netloc:
        raise RuntimeError(f"Unable to parse netloc from base_url: {client.base_url!r}")

    def looks_like_static_asset(path: str) -> bool:
        lower = path.lower()
        return (
            "/assets/" in lower
            or lower.endswith(".js")
            or lower.endswith(".mjs")
            or lower.endswith(".css")
        )

    resolved_assets: list[str] = []
    for asset_url in parser.asset_urls:
        absolute = urljoin(homepage_url, asset_url)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if not looks_like_static_asset(parsed.path):
            continue
        # Same-origin for smoke-test purposes: same scheme/host/port.
        if parsed.netloc != base_netloc:
            continue
        resolved_assets.append(absolute)

    unique_assets = list(dict.fromkeys(resolved_assets))
    log(
        "Assets discovered: "
        f"raw={len(parser.asset_urls)} candidates={len(resolved_assets)} unique={len(unique_assets)}"
    )
    if not unique_assets:
        raw_assets = list(dict.fromkeys(parser.asset_urls))[:10]
        raise RuntimeError(
            "No loadable same-origin JS/CSS assets found in homepage HTML "
            f"(base_netloc={base_netloc!r}, found={raw_assets!r})"
        )

    for asset_url in unique_assets[:1]:
        log(f"Fetching asset: {asset_url}")
        asset_status, _, asset_body = client.get(
            asset_url,
            headers={"Accept": "*/*"},
            timeout_seconds=20.0,
        )
        if asset_status != 200:
            raise RuntimeError(
                f"Asset returned non-200: {asset_status} ({asset_url}, preview={_preview_bytes(asset_body)!r})"
            )
        if not asset_body:
            raise RuntimeError(f"Asset returned empty body: {asset_url}")

    log("Web checks passed (assets fetched: 1)")


def wait_for_health(client: HttpClient, max_attempts: int = 30, delay: float = 2.0) -> bool:
    """Wait for /health to return healthy status."""
    url = f"{client.base_url}/health"

    for attempt in range(1, max_attempts + 1):
        try:
            status, _, body = client.get(url, timeout_seconds=10.0)
            if status == 200:
                data = json.loads(body.decode())
                if data.get("status") == "healthy":
                    log(f"Health check passed (attempt {attempt})")
                    return True
        except (json.JSONDecodeError, RuntimeError):
            pass

        if attempt < max_attempts:
            time.sleep(delay)

    return False


def solve_pow(nonce: str, payload_hash: str, difficulty: int) -> int:
    """
    Solve proof-of-work challenge.

    Finds counter where SHA256(nonce || counter_hex || payload_hash) has
    'difficulty' leading zero bits.
    """
    target = 2 ** (256 - difficulty)

    counter = 0
    start_time = time.time()

    while True:
        preimage = f"{nonce}{counter:016x}{payload_hash}"
        hash_bytes = hashlib.sha256(preimage.encode()).digest()
        hash_int = int.from_bytes(hash_bytes, "big")

        if hash_int < target:
            elapsed = time.time() - start_time
            log(f"PoW solved: counter={counter} ({elapsed:.2f}s, {counter/elapsed:.0f} H/s)")
            return counter

        counter += 1

        if counter % 1_000_000 == 0:
            elapsed = time.time() - start_time
            log(f"PoW progress: {counter:,} attempts ({counter/elapsed:.0f} H/s)")


def generate_test_secret() -> tuple[str, str, str, str]:
    """
    Generate fake encrypted data for testing.

    Returns (ciphertext_b64, iv_b64, auth_tag_b64, payload_hash)
    """
    ciphertext = b"smoke-test-" + secrets.token_bytes(21)  # 32 bytes total
    iv = secrets.token_bytes(12)
    auth_tag = secrets.token_bytes(16)

    ciphertext_b64 = base64.b64encode(ciphertext).decode()
    iv_b64 = base64.b64encode(iv).decode()
    auth_tag_b64 = base64.b64encode(auth_tag).decode()

    payload_hash = hashlib.sha256(ciphertext + iv + auth_tag).hexdigest()

    return ciphertext_b64, iv_b64, auth_tag_b64, payload_hash


def encrypt_aes_gcm(plaintext: bytes, key: bytes) -> tuple[str, str, str]:
    """
    Encrypt bytes with AES-256-GCM.

    Returns (ciphertext_b64, iv_b64, auth_tag_b64).
    Requires cryptography library.
    """
    iv = secrets.token_bytes(12)
    aesgcm = AESGCM(key)
    # AESGCM.encrypt returns ciphertext + tag concatenated (tag is last 16 bytes)
    ct_with_tag = aesgcm.encrypt(iv, plaintext, None)
    ciphertext = ct_with_tag[:-16]
    auth_tag = ct_with_tag[-16:]
    return (
        base64.b64encode(ciphertext).decode(),
        base64.b64encode(iv).decode(),
        base64.b64encode(auth_tag).decode(),
    )


def generate_encrypted_attachment(key: bytes) -> dict[str, Any]:
    """
    Generate encrypted attachment payload for upload testing.

    Returns dict suitable for POST /api/v1/attachments/upload.
    """
    # Fake file content (small for smoke test)
    blob = b"smoke-test-attachment-" + secrets.token_bytes(100)
    metadata = json.dumps({"name": "smoke-test.txt", "type": "text/plain"}).encode()

    blob_ct, blob_iv, blob_tag = encrypt_aes_gcm(blob, key)
    meta_ct, meta_iv, meta_tag = encrypt_aes_gcm(metadata, key)

    return {
        "encrypted_blob": blob_ct,
        "blob_iv": blob_iv,
        "blob_auth_tag": blob_tag,
        "encrypted_metadata": meta_ct,
        "metadata_iv": meta_iv,
        "metadata_auth_tag": meta_tag,
        "position": 0,
    }


@dataclass
class SmokeContext:
    client: HttpClient
    max_health_attempts: int

    edit_token: str | None = None
    decrypt_token: str | None = None
    secret_id: str | None = None
    unlock_at: datetime | None = None
    expires_at: datetime | None = None
    decrypt_status: dict[str, Any] | None = None

    # Attachment fields for file upload smoke test
    attachment_id: str | None = None
    attachment_key: bytes | None = None

    # Capability token fields
    capability_token_api_key: str | None = None

    def require_edit_token(self) -> str:
        if not self.edit_token:
            raise RuntimeError("Missing edit_token (step ordering bug)")
        return self.edit_token

    def require_decrypt_token(self) -> str:
        if not self.decrypt_token:
            raise RuntimeError("Missing decrypt_token (step ordering bug)")
        return self.decrypt_token

    def require_secret_id(self) -> str:
        if not self.secret_id:
            raise RuntimeError("Missing secret_id (step ordering bug)")
        return self.secret_id

    def require_unlock_at(self) -> datetime:
        if not self.unlock_at:
            raise RuntimeError("Missing unlock_at (step ordering bug)")
        return self.unlock_at

    def require_expires_at(self) -> datetime:
        if not self.expires_at:
            raise RuntimeError("Missing expires_at (step ordering bug)")
        return self.expires_at

    def require_decrypt_status(self) -> dict[str, Any]:
        if self.decrypt_status is None:
            raise RuntimeError("Missing decrypt_status (step ordering bug)")
        return self.decrypt_status


@dataclass(frozen=True)
class Step:
    name: str
    run: Callable[[SmokeContext], None]
    # Return `None` to run the step; return a string to skip with that reason.
    skip_reason: SkipCheck | None = None


@dataclass(frozen=True)
class StepResult:
    name: str
    status: str  # passed|skipped|failed
    seconds: float
    detail: str | None = None


def _print_summary(results: list[StepResult], total_seconds: float) -> None:
    log("Summary:")
    for result in results:
        suffix = f" - {result.detail}" if result.detail else ""
        log(f"  {result.status.upper():7} {result.name} ({result.seconds:.2f}s){suffix}")
    log(f"Total: {total_seconds:.2f}s")


def run_steps(ctx: SmokeContext, steps: list[Step]) -> bool:
    results: list[StepResult] = []
    overall_start = time.time()

    for step in steps:
        reason = step.skip_reason(ctx) if step.skip_reason else None
        if reason:
            log(f"SKIP: {step.name}: {reason}")
            results.append(StepResult(step.name, "skipped", 0.0, reason))
            continue

        log(f"STEP: {step.name}")
        start = time.time()
        try:
            step.run(ctx)
        except Exception as e:
            elapsed = time.time() - start
            results.append(StepResult(step.name, "failed", elapsed, str(e)))
            _print_summary(results, time.time() - overall_start)
            return False

        elapsed = time.time() - start
        results.append(StepResult(step.name, "passed", elapsed))
        log(f"OK: {step.name} ({elapsed:.2f}s)")

    _print_summary(results, time.time() - overall_start)
    return True


def step_health(ctx: SmokeContext) -> None:
    log(f"Checking health: {ctx.client.base_url}/health")
    if not wait_for_health(ctx.client, max_attempts=ctx.max_health_attempts):
        raise RuntimeError("Health check failed")


def step_web(ctx: SmokeContext) -> None:
    check_web_serving(ctx.client)


def step_upload_attachment(ctx: SmokeContext) -> None:
    """Upload an encrypted attachment before secret creation."""
    if not HAS_CRYPTO:
        log("cryptography not installed; skipping attachment upload")
        return

    log("Generating encrypted attachment")
    ctx.attachment_key = secrets.token_bytes(32)
    payload = generate_encrypted_attachment(ctx.attachment_key)

    log("Uploading attachment")
    try:
        result = ctx.client.api_json("POST", "/attachments/upload", data=payload)
        ctx.attachment_id = result["attachment_id"]
        storage_key = result.get("storage_key", "")
        log(f"Attachment uploaded: id={ctx.attachment_id}, key={storage_key[:30]}...")
    except ApiError as e:
        if e.status_code == 503:
            # Object storage not enabled on this environment
            log("Object storage not enabled; skipping attachment tests")
            ctx.attachment_id = None
            return
        raise


def step_create_secret(ctx: SmokeContext) -> None:
    log("Generating test secret data")
    ciphertext_b64, iv_b64, auth_tag_b64, payload_hash = generate_test_secret()
    ciphertext_size = len(base64.b64decode(ciphertext_b64))

    ctx.edit_token = secrets.token_hex(32)
    ctx.decrypt_token = secrets.token_hex(32)

    log("Requesting PoW challenge")
    challenge = ctx.client.api_json(
        "POST",
        "/challenges",
        data={"payload_hash": payload_hash, "ciphertext_size": ciphertext_size},
    )
    log(f"Got challenge: difficulty={challenge['difficulty']}, expires={challenge['expires_at']}")

    log(f"Solving PoW (difficulty={challenge['difficulty']})")
    counter = solve_pow(challenge["nonce"], payload_hash, challenge["difficulty"])

    now = datetime.now(timezone.utc)
    unlock_at = (now + timedelta(seconds=DEFAULT_UNLOCK_SECONDS)).replace(microsecond=0)
    expires_at = (unlock_at + timedelta(minutes=EXPIRY_GAP_MINUTES)).replace(microsecond=0)

    log("Creating secret")
    create_payload = {
        "ciphertext": ciphertext_b64,
        "iv": iv_b64,
        "auth_tag": auth_tag_b64,
        "unlock_at": format_utc_datetime(unlock_at),
        "expires_at": format_utc_datetime(expires_at),
        "edit_token": ctx.require_edit_token(),
        "decrypt_token": ctx.require_decrypt_token(),
        "pow_proof": {
            "challenge_id": challenge["challenge_id"],
            "nonce": challenge["nonce"],
            "counter": counter,
            "payload_hash": payload_hash,
        },
    }

    # Include attachment if one was uploaded
    if ctx.attachment_id:
        create_payload["attachment_ids"] = [ctx.attachment_id]
        log(f"Including attachment: {ctx.attachment_id}")

    try:
        secret = ctx.client.api_json("POST", "/secrets", data=create_payload)
    except ApiError as e:
        adjusted_unlock_at = compute_unlock_at_for_environment(e)
        if not adjusted_unlock_at:
            raise
        unlock_at = adjusted_unlock_at.replace(microsecond=0)
        expires_at = (unlock_at + timedelta(minutes=EXPIRY_GAP_MINUTES)).replace(microsecond=0)
        create_payload["unlock_at"] = format_utc_datetime(unlock_at)
        create_payload["expires_at"] = format_utc_datetime(expires_at)
        log(f"Create rejected; retrying with unlock_at={create_payload['unlock_at']}")
        secret = ctx.client.api_json("POST", "/secrets", data=create_payload)

    ctx.secret_id = secret["secret_id"]
    ctx.unlock_at = parse_utc_datetime(secret["unlock_at"])
    ctx.expires_at = parse_utc_datetime(secret["expires_at"])
    log(f"Secret created: id={ctx.secret_id}, unlock_at={secret['unlock_at']}")


def step_edit_status(ctx: SmokeContext) -> None:
    log("Checking secret status via edit token")
    status = ctx.client.api_json(
        "GET",
        "/secrets/edit/status",
        headers={"Authorization": f"Bearer {ctx.require_edit_token()}"},
    )
    if not status.get("exists"):
        raise RuntimeError("Secret not found via edit token")
    if status.get("status") != "pending":
        raise RuntimeError(f"Expected status 'pending', got '{status.get('status')}'")

    status_unlock_at = parse_utc_datetime(status["unlock_at"])
    status_expires_at = parse_utc_datetime(status["expires_at"])
    if not assert_timestamps_match(
        "Status timestamps do not match create response",
        ctx.require_unlock_at(),
        ctx.require_expires_at(),
        status_unlock_at,
        status_expires_at,
    ):
        raise RuntimeError("Status timestamps mismatch")

    log(f"Status verified: exists={status['exists']}, status={status['status']}")


def step_edit_flow(ctx: SmokeContext) -> None:
    log("Editing secret dates via edit token")
    created_unlock_at = ctx.require_unlock_at()
    created_expires_at = ctx.require_expires_at()

    new_unlock_at = (created_unlock_at + timedelta(seconds=EDIT_POSTPONE_SECONDS)).replace(microsecond=0)
    new_expires_at = (created_expires_at + timedelta(seconds=EDIT_POSTPONE_SECONDS)).replace(microsecond=0)

    if new_unlock_at >= new_expires_at:
        raise RuntimeError("Computed invalid edited timestamps (unlock >= expiry)")
    if (new_expires_at - new_unlock_at) < timedelta(minutes=15):
        raise RuntimeError("Computed invalid edited timestamps (gap < 15 minutes)")

    edited = ctx.client.api_json(
        "PUT",
        "/secrets/edit",
        headers={"Authorization": f"Bearer {ctx.require_edit_token()}"},
        data={"unlock_at": format_utc_datetime(new_unlock_at), "expires_at": format_utc_datetime(new_expires_at)},
    )

    edited_unlock_at = parse_utc_datetime(edited["unlock_at"])
    edited_expires_at = parse_utc_datetime(edited["expires_at"])
    if not assert_timestamps_match(
        "Edit response timestamps do not match request",
        new_unlock_at,
        new_expires_at,
        edited_unlock_at,
        edited_expires_at,
    ):
        raise RuntimeError("Edit response timestamps mismatch")

    if edited_unlock_at <= created_unlock_at or edited_expires_at <= created_expires_at:
        raise RuntimeError("Edit did not postpone timestamps as expected")

    log("Re-checking secret edit status after edit")
    status2 = ctx.client.api_json(
        "GET",
        "/secrets/edit/status",
        headers={"Authorization": f"Bearer {ctx.require_edit_token()}"},
    )
    if not status2.get("exists"):
        raise RuntimeError("Secret not found via edit token after edit")
    if status2.get("status") != "pending":
        raise RuntimeError(f"Expected status 'pending' after edit, got '{status2.get('status')}'")

    status2_unlock_at = parse_utc_datetime(status2["unlock_at"])
    status2_expires_at = parse_utc_datetime(status2["expires_at"])
    if not assert_timestamps_match(
        "Status timestamps do not reflect edit",
        edited_unlock_at,
        edited_expires_at,
        status2_unlock_at,
        status2_expires_at,
    ):
        raise RuntimeError("Status timestamps did not reflect edit")

    ctx.unlock_at = edited_unlock_at
    ctx.expires_at = edited_expires_at


def step_decrypt_status(ctx: SmokeContext) -> None:
    log("Checking secret status via decrypt token")
    decrypt_status = ctx.client.api_json(
        "GET",
        "/secrets/status",
        headers={"Authorization": f"Bearer {ctx.require_decrypt_token()}"},
    )
    if not decrypt_status.get("exists"):
        raise RuntimeError("Secret not found via decrypt token")
    if decrypt_status.get("status") not in ("pending", "available"):
        raise RuntimeError(f"Unexpected decrypt status '{decrypt_status.get('status')}'")
    ctx.decrypt_status = decrypt_status


def step_public_status(ctx: SmokeContext) -> None:
    log("Checking secret status via public ID endpoint")
    secret_id = ctx.require_secret_id()
    public_status = ctx.client.api_json("GET", f"/secrets/{secret_id}/status")
    if public_status.get("id") != secret_id:
        raise RuntimeError("Public status endpoint returned mismatched secret id")

    decrypt_status = ctx.require_decrypt_status()
    expected_public_status = (
        "unlocked" if decrypt_status.get("status") == "available" else decrypt_status.get("status")
    )
    if public_status.get("status") != expected_public_status:
        raise RuntimeError(
            f"Expected public status '{expected_public_status}', got '{public_status.get('status')}'"
        )


def step_optional_unlock_mapping(ctx: SmokeContext) -> None:
    log("Waiting briefly for unlock to verify status mapping")
    deadline = time.time() + UNLOCK_POLL_DEADLINE_SECONDS
    while time.time() < deadline:
        current = ctx.client.api_json(
            "GET",
            "/secrets/status",
            headers={"Authorization": f"Bearer {ctx.require_decrypt_token()}"},
        )
        if current.get("exists") and current.get("status") == "available":
            secret_id = ctx.require_secret_id()
            public_current = ctx.client.api_json("GET", f"/secrets/{secret_id}/status")
            if public_current.get("status") != "unlocked":
                raise RuntimeError(
                    f"Expected public status 'unlocked' after available, got '{public_current.get('status')}'"
                )
            return
        time.sleep(UNLOCK_POLL_SLEEP_SECONDS)

    log("Deadline reached without unlock; skipping status mapping verification")


def step_capability_token_flow(ctx: SmokeContext) -> None:
    """Mint a capability token, validate it, create a secret without PoW, verify consumed."""
    api_key = ctx.capability_token_api_key
    assert api_key  # skip check ensures this

    # Step 1: Mint token
    log("Minting capability token (tier=basic)")
    try:
        token_resp = ctx.client.api_json(
            "POST",
            "/capability-tokens",
            headers={"X-API-Key": api_key},
            data={"tier": "basic"},
        )
    except ApiError as e:
        if e.status_code == 503:
            log("Capability tokens not configured on this environment; skipping")
            return
        raise

    token = token_resp.get("token")
    if not token or len(token) != 64:
        raise RuntimeError(f"Expected 64-char token, got: {token!r}")
    tier = token_resp.get("tier")
    if tier != "basic":
        raise RuntimeError(f"Expected tier 'basic', got {tier!r}")
    log(f"Token minted: tier={tier}, prefix={token[:8]}...")

    # Step 2: Validate token (should be valid, not consumed)
    log("Validating token (pre-use)")
    validate_resp = ctx.client.api_json(
        "GET",
        "/capability-tokens/validate",
        headers={"X-Capability-Token": token},
    )
    if not validate_resp.get("valid"):
        raise RuntimeError(f"Token should be valid before use: {validate_resp!r}")
    if validate_resp.get("consumed"):
        raise RuntimeError(f"Token should not be consumed yet: {validate_resp!r}")

    # Step 3: Create secret using token (no PoW)
    log("Creating secret with capability token (no PoW)")
    ciphertext_b64, iv_b64, auth_tag_b64, _ = generate_test_secret()
    now = datetime.now(timezone.utc)
    unlock_at = (now + timedelta(seconds=DEFAULT_UNLOCK_SECONDS)).replace(microsecond=0)
    expires_at = (unlock_at + timedelta(minutes=EXPIRY_GAP_MINUTES)).replace(microsecond=0)

    edit_token = secrets.token_hex(32)
    decrypt_token = secrets.token_hex(32)

    create_payload: dict[str, Any] = {
        "ciphertext": ciphertext_b64,
        "iv": iv_b64,
        "auth_tag": auth_tag_b64,
        "unlock_at": format_utc_datetime(unlock_at),
        "expires_at": format_utc_datetime(expires_at),
        "edit_token": edit_token,
        "decrypt_token": decrypt_token,
    }

    try:
        secret = ctx.client.api_json(
            "POST",
            "/secrets",
            headers={"X-Capability-Token": token},
            data=create_payload,
        )
    except ApiError as e:
        adjusted = compute_unlock_at_for_environment(e)
        if not adjusted:
            raise
        unlock_at = adjusted.replace(microsecond=0)
        expires_at = (unlock_at + timedelta(minutes=EXPIRY_GAP_MINUTES)).replace(microsecond=0)
        create_payload["unlock_at"] = format_utc_datetime(unlock_at)
        create_payload["expires_at"] = format_utc_datetime(expires_at)
        log(f"Create rejected; retrying with unlock_at={create_payload['unlock_at']}")
        secret = ctx.client.api_json(
            "POST",
            "/secrets",
            headers={"X-Capability-Token": token},
            data=create_payload,
        )

    if not secret.get("secret_id"):
        raise RuntimeError(f"Secret creation with token failed: {secret!r}")
    log(f"Secret created via token: id={secret['secret_id']}")

    # Step 4: Verify token is now consumed
    log("Validating token (post-use, should be consumed)")
    validate_after = ctx.client.api_json(
        "GET",
        "/capability-tokens/validate",
        headers={"X-Capability-Token": token},
    )
    if validate_after.get("valid"):
        raise RuntimeError(f"Token should be invalid after consumption: {validate_after!r}")
    if not validate_after.get("consumed"):
        raise RuntimeError(f"Token should show consumed=true: {validate_after!r}")

    # Step 5: Verify invalid token is rejected on secret creation
    log("Verifying invalid token rejected")
    bad_token = "0" * 64
    status, _, body = ctx.client.request(
        "POST",
        f"{ctx.client.base_url}/api/v1/secrets",
        headers={
            "Content-Type": "application/json",
            "X-Capability-Token": bad_token,
        },
        body=json.dumps(create_payload).encode(),
    )
    if status not in (401, 400):
        raise RuntimeError(f"Expected 401/400 for invalid token, got {status}")

    log("Capability token flow OK")


def step_feedback(ctx: SmokeContext) -> None:
    """Send a minimal feedback payload and verify 201 + response shape."""
    log("Submitting smoke-test feedback")
    result = ctx.client.api_json(
        "POST",
        "/feedback",
        data={"message": "[smoke-test] automated probe — safe to ignore"},
    )
    if not result.get("success"):
        raise RuntimeError(f"Feedback response missing success=true: {result!r}")
    if "message" not in result:
        raise RuntimeError(f"Feedback response missing 'message' field: {result!r}")
    log("Feedback endpoint OK")


def step_retrieve_pending(ctx: SmokeContext) -> None:
    log("Verifying retrieve endpoint returns pending pre-unlock")
    current = ctx.client.api_json(
        "GET",
        "/secrets/status",
        headers={"Authorization": f"Bearer {ctx.require_decrypt_token()}"},
    )
    if not current.get("exists"):
        raise RuntimeError(f"Unexpected status before retrieve: {current!r}")
    if current.get("status") == "available":
        log("Secret already unlocked; skipping pending retrieve assertion to avoid consuming one-time retrieval")
        return
    if current.get("status") != "pending":
        raise RuntimeError(f"Unexpected status before retrieve: {current!r}")

    status, _, body = ctx.client.request(
        "GET",
        f"{ctx.client.base_url}/api/v1/secrets/retrieve",
        headers={"Authorization": f"Bearer {ctx.require_decrypt_token()}"},
    )
    if status != 403:
        raise RuntimeError(f"Expected 403 pending from retrieve, got {status} (preview={_preview_bytes(body)!r})")
    try:
        payload = json.loads(body.decode())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Expected JSON error body from retrieve: preview={_preview_bytes(body)!r}") from e

    detail = payload.get("detail")
    if not isinstance(detail, dict):
        raise RuntimeError(f"Expected JSON detail object from retrieve: payload={payload!r}")
    if detail.get("status") != "pending":
        raise RuntimeError(f"Expected retrieve status 'pending', got {detail.get('status')!r}")
    if "unlock_at" in detail:
        unlock_at = parse_utc_datetime(str(detail["unlock_at"]))
        if unlock_at != ctx.require_unlock_at():
            raise RuntimeError(
                "Retrieve pending unlock_at mismatch: "
                f"expected={ctx.require_unlock_at().isoformat()} actual={unlock_at.isoformat()}"
            )


def step_retrieve_available_once(ctx: SmokeContext) -> None:
    log("Waiting for unlock then retrieving (one-time delete)")

    deadline = time.time() + UNLOCK_POLL_DEADLINE_SECONDS
    while time.time() < deadline:
        current = ctx.client.api_json(
            "GET",
            "/secrets/status",
            headers={"Authorization": f"Bearer {ctx.require_decrypt_token()}"},
        )
        if current.get("exists") and current.get("status") == "available":
            break
        time.sleep(UNLOCK_POLL_SLEEP_SECONDS)
    else:
        raise RuntimeError("Secret did not unlock before retrieve deadline")

    retrieved = ctx.client.api_json(
        "GET",
        "/secrets/retrieve",
        headers={"Authorization": f"Bearer {ctx.require_decrypt_token()}"},
    )
    if retrieved.get("status") != "available":
        raise RuntimeError(f"Expected retrieve status 'available', got {retrieved.get('status')!r}")
    for field in ("ciphertext", "iv", "auth_tag"):
        if not retrieved.get(field):
            raise RuntimeError(f"Retrieve response missing {field}")

    # Verify attachment if one was uploaded
    if ctx.attachment_id:
        attachments = retrieved.get("attachments", [])
        if not attachments:
            raise RuntimeError("Expected attachment in retrieve response but got none")
        att = attachments[0]
        if not att.get("presigned_url"):
            raise RuntimeError("Attachment missing presigned_url")
        if not att.get("storage_key"):
            raise RuntimeError("Attachment missing storage_key")
        log(f"Attachment verified: presigned URL present for {att.get('storage_key', '')[:30]}...")

        # Fetch the presigned URL to verify the download actually works
        presigned_url = att["presigned_url"]
        log("Fetching attachment via presigned URL")
        dl_status, _, dl_body = ctx.client.get(presigned_url, timeout_seconds=20.0)
        if dl_status != 200:
            raise RuntimeError(f"Attachment download failed: status={dl_status}")
        if not dl_body:
            raise RuntimeError("Attachment download returned empty body")
        log(f"Attachment downloaded: {len(dl_body)} bytes")

    after = ctx.client.api_json(
        "GET",
        "/secrets/status",
        headers={"Authorization": f"Bearer {ctx.require_decrypt_token()}"},
    )
    if after.get("exists") or after.get("status") != "not_found":
        raise RuntimeError(f"Expected status not_found after retrieve, got {after!r}")

    status2, _, body2 = ctx.client.request(
        "GET",
        f"{ctx.client.base_url}/api/v1/secrets/retrieve",
        headers={"Authorization": f"Bearer {ctx.require_decrypt_token()}"},
    )
    if status2 not in (404, 410):
        raise RuntimeError(f"Expected 404/410 on second retrieve, got {status2} (preview={_preview_bytes(body2)!r})")

    secret_id = ctx.require_secret_id()
    public_status = ctx.client.api_json("GET", f"/secrets/{secret_id}/status")
    if public_status.get("status") != "retrieved":
        raise RuntimeError(f"Expected public status 'retrieved' after retrieve, got '{public_status.get('status')}'")


def skip_optional_unlock_mapping(ctx: SmokeContext) -> str | None:
    if not ctx.unlock_at:
        return "missing unlock_at"
    seconds_until_unlock = (ctx.unlock_at - datetime.now(timezone.utc)).total_seconds()
    if 0 < seconds_until_unlock <= UNLOCK_SOON_MAX_SECONDS:
        return None
    return "unlock not soon"


def skip_retrieve_lifecycle(ctx: SmokeContext) -> str | None:
    return skip_optional_unlock_mapping(ctx)


def skip_capability_token_disabled(ctx: SmokeContext) -> str | None:
    if not ctx.capability_token_api_key:
        return "no --capability-token-key provided"
    return None


def skip_feedback_disabled(_: SmokeContext) -> str | None:
    return "disabled (use --test-feedback to enable)"


def skip_web_disabled(_: SmokeContext) -> str | None:
    return "disabled via --skip-web"


def main() -> int:
    parser = argparse.ArgumentParser(description="IEOMD smoke test")
    parser.add_argument("base_url", help="Base URL (e.g., https://staging.example.com)")
    parser.add_argument(
        "--health-only",
        action="store_true",
        help="Only run health check, skip full flow",
    )
    parser.add_argument(
        "--skip-web",
        action="store_true",
        help="Skip web homepage/assets checks (not recommended for staging/prod)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout seconds (default: {DEFAULT_TIMEOUT_SECONDS:g})",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"Retries for transient failures (default: {DEFAULT_RETRIES})",
    )
    parser.add_argument(
        "--test-feedback",
        action="store_true",
        help="Enable feedback endpoint check (off by default to avoid notification spam)",
    )
    parser.add_argument(
        "--capability-token-key",
        default=None,
        help="Internal API key for capability-token smoke test (skipped if not provided)",
    )
    parser.add_argument(
        "--max-health-attempts",
        type=int,
        default=30,
        help="Max health check attempts (default: 30)",
    )
    args = parser.parse_args()

    try:
        base_url = args.base_url.rstrip("/")
        client = HttpClient(base_url=base_url, timeout_seconds=args.timeout, retries=args.retries)
        ctx = SmokeContext(
            client=client,
            max_health_attempts=args.max_health_attempts,
            capability_token_api_key=args.capability_token_key,
        )

        steps: list[Step] = [Step("health", step_health)]
        if args.health_only:
            log("Health-only mode: skipping full flow")
        else:
            steps.extend(
                [
                    Step(
                        "feedback",
                        step_feedback,
                        skip_reason=None if args.test_feedback else skip_feedback_disabled,
                    ),
                    Step(
                        "web",
                        step_web,
                        skip_reason=skip_web_disabled if args.skip_web else None,
                    ),
                    Step("upload attachment", step_upload_attachment),
                    Step("create secret", step_create_secret),
                    Step("edit status", step_edit_status),
                    Step("edit flow", step_edit_flow),
                    Step("decrypt status", step_decrypt_status),
                    Step("public status", step_public_status),
                    Step(
                        "retrieve pending",
                        step_retrieve_pending,
                        skip_reason=skip_retrieve_lifecycle,
                    ),
                    Step(
                        "optional unlock mapping",
                        step_optional_unlock_mapping,
                        skip_reason=skip_optional_unlock_mapping,
                    ),
                    Step(
                        "retrieve available + delete",
                        step_retrieve_available_once,
                        skip_reason=skip_retrieve_lifecycle,
                    ),
                    Step(
                        "capability token flow",
                        step_capability_token_flow,
                        skip_reason=skip_capability_token_disabled,
                    ),
                ]
            )

        ok = run_steps(ctx, steps)
        return 0 if ok else 1
    except Exception as e:
        log(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
