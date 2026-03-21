import base64

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.exceptions import ETagMismatchError, VaultBlobTooLargeError, VaultExistsError
from app.middleware.rate_limit import limiter
from app.schemas.vault import VaultGetOut, VaultPutIn, VaultPutOut
from app.services.vault_service import (
    create_vault,
    get_vault_or_404,
    update_vault,
)

router = APIRouter(tags=["vault"])
logger = structlog.get_logger()


def _extract_sync_token(authorization: str = Header(...)) -> str:
    """Extract syncToken from Authorization: Bearer header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    return authorization[7:]


def _validate_vault_id(vault_id: str) -> None:
    """Validate vault_id is a 64-char hex string (SHA-256 hash)."""
    if len(vault_id) != 64 or not all(c in "0123456789abcdef" for c in vault_id):
        raise HTTPException(status_code=400, detail="Invalid vault_id format")


@router.get("/vault/{vault_id}", response_model=VaultGetOut)
@limiter.limit("30/minute")
async def get_vault_blob(
    request: Request,
    vault_id: str,
    authorization: str = Header(...),
    db: Session = Depends(get_db),
):
    """Fetch the encrypted vault blob. Requires syncToken."""
    _validate_vault_id(vault_id)
    sync_token = _extract_sync_token(authorization)
    vault = get_vault_or_404(db, vault_id, sync_token)

    logger.info("vault_read", vault_id=vault_id[:8])

    return Response(
        content=VaultGetOut(
            ciphertext=base64.b64encode(vault.ciphertext).decode(),
            etag=vault.etag,
        ).model_dump_json(),
        media_type="application/json",
        headers={"ETag": f'"{vault.etag}"'},
    )


@router.put("/vault/{vault_id}", response_model=VaultPutOut)
@limiter.limit("10/minute")
async def put_vault_blob(
    request: Request,
    vault_id: str,
    body: VaultPutIn,
    authorization: str = Header(...),
    if_match: str | None = Header(None, alias="If-Match"),
    if_none_match: str | None = Header(None, alias="If-None-Match"),
    db: Session = Depends(get_db),
):
    """Create or update the encrypted vault blob."""
    _validate_vault_id(vault_id)
    sync_token = _extract_sync_token(authorization)

    # Bootstrap: first write with If-None-Match: *
    if if_none_match == "*":
        try:
            vault, etag = create_vault(db, vault_id, body.ciphertext, sync_token)
        except VaultExistsError:
            raise HTTPException(status_code=412, detail="Vault already exists")
        except VaultBlobTooLargeError as e:
            raise HTTPException(status_code=400, detail=str(e))

        logger.info("vault_created", vault_id=vault_id[:8])
        return Response(
            content=VaultPutOut(etag=etag, created=True).model_dump_json(),
            status_code=201,
            media_type="application/json",
            headers={"ETag": f'"{etag}"'},
        )

    # Normal update: requires If-Match
    if not if_match:
        raise HTTPException(status_code=428, detail="If-Match or If-None-Match header required")

    # Strip quotes from ETag header value
    etag_value = if_match.strip('"')
    vault = get_vault_or_404(db, vault_id, sync_token)

    try:
        vault, new_etag = update_vault(db, vault, body.ciphertext, etag_value)
    except ETagMismatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except VaultBlobTooLargeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("vault_updated", vault_id=vault_id[:8])
    return Response(
        content=VaultPutOut(etag=new_etag, created=False).model_dump_json(),
        status_code=200,
        media_type="application/json",
        headers={"ETag": f'"{new_etag}"'},
    )
