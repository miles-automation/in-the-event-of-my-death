import base64

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.vault import VaultGetResponse, VaultPutRequest, VaultPutResponse
from app.services.vault_service import (
    create_vault,
    get_vault,
    update_vault,
    verify_sync_token,
)

router = APIRouter()
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


@router.get("/vault/{vault_id}", response_model=VaultGetResponse)
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

    vault = get_vault(db, vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")

    if not verify_sync_token(vault, sync_token):
        # Return 404 instead of 401 to avoid confirming vault existence
        raise HTTPException(status_code=404, detail="Vault not found")

    logger.info("vault_read", vault_id=vault_id[:8])

    return Response(
        content=VaultGetResponse(
            ciphertext=base64.b64encode(vault.ciphertext).decode(),
            etag=vault.etag,
        ).model_dump_json(),
        media_type="application/json",
        headers={"ETag": f'"{vault.etag}"'},
    )


@router.put("/vault/{vault_id}", response_model=VaultPutResponse)
@limiter.limit("10/minute")
async def put_vault_blob(
    request: Request,
    vault_id: str,
    body: VaultPutRequest,
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
        except ValueError as e:
            if "already exists" in str(e):
                raise HTTPException(status_code=412, detail="Vault already exists")
            raise HTTPException(status_code=400, detail=str(e))

        logger.info("vault_created", vault_id=vault_id[:8])
        return Response(
            content=VaultPutResponse(etag=etag, created=True).model_dump_json(),
            status_code=201,
            media_type="application/json",
            headers={"ETag": f'"{etag}"'},
        )

    # Normal update: requires If-Match
    if not if_match:
        raise HTTPException(status_code=428, detail="If-Match or If-None-Match header required")

    # Strip quotes from ETag header value
    etag_value = if_match.strip('"')

    vault = get_vault(db, vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")

    if not verify_sync_token(vault, sync_token):
        raise HTTPException(status_code=404, detail="Vault not found")

    try:
        vault, new_etag = update_vault(db, vault, body.ciphertext, etag_value)
    except ValueError as e:
        if "ETag mismatch" in str(e):
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("vault_updated", vault_id=vault_id[:8])
    return Response(
        content=VaultPutResponse(etag=new_etag, created=False).model_dump_json(),
        status_code=200,
        media_type="application/json",
        headers={"ETag": f'"{new_etag}"'},
    )
