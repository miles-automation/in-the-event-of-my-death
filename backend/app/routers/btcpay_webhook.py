"""BTCPay Server webhook handler for payment notifications."""

import hashlib
import hmac

import structlog
from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.database import SessionLocal
from app.services.capability_token_service import create_capability_token

router = APIRouter()
logger = structlog.get_logger()


def verify_btcpay_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify BTCPay webhook signature.

    BTCPay uses HMAC-SHA256 with the webhook secret.
    The signature header format is: sha256=<hex_digest>
    """
    if not signature.startswith("sha256="):
        return False

    expected_sig = signature[7:]  # Remove "sha256=" prefix
    computed_sig = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_sig, expected_sig)


@router.post("/btcpay-webhook")
async def handle_btcpay_webhook(
    request: Request,
    btcpay_sig: str = Header(None, alias="BTCPay-Sig"),
):
    """
    Handle BTCPay webhook notifications.

    Creates capability tokens when invoices are settled.
    """
    # Check if webhook is configured
    if not settings.btcpay_webhook_secret:
        logger.warning("btcpay_webhook_not_configured")
        raise HTTPException(status_code=503, detail="Webhook not configured")

    # Get raw body for signature verification
    body = await request.body()

    # Verify signature
    if not btcpay_sig or not verify_btcpay_signature(
        body, btcpay_sig, settings.btcpay_webhook_secret
    ):
        logger.warning("btcpay_webhook_invalid_signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse the webhook payload
    try:
        payload = await request.json()
    except Exception:
        logger.error("btcpay_webhook_invalid_json")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("type")
    invoice_id = payload.get("invoiceId")

    logger.info(
        "btcpay_webhook_received",
        event_type=event_type,
        invoice_id=invoice_id,
    )

    # Only process settled invoices
    if event_type != "InvoiceSettled":
        # Acknowledge but don't process other events
        return {"status": "ignored", "reason": f"Event type {event_type} not handled"}

    # Check if we already processed this invoice (idempotency)
    # The payment_reference field stores the invoice ID
    db = SessionLocal()
    try:
        from app.models.capability_token import CapabilityToken

        existing = (
            db.query(CapabilityToken)
            .filter(
                CapabilityToken.payment_provider == "btcpay",
                CapabilityToken.payment_reference == invoice_id,
            )
            .first()
        )

        if existing:
            logger.info(
                "btcpay_webhook_already_processed",
                invoice_id=invoice_id,
                token_id=existing.id,
            )
            return {"status": "already_processed", "invoice_id": invoice_id}

        # Create capability token for the premium tier
        token_model, raw_token = create_capability_token(
            db=db,
            tier="premium",
            payment_provider="btcpay",
            payment_reference=invoice_id,
            token_metadata={
                "amount": payload.get("amount"),
                "currency": payload.get("currency"),
            },
        )

        # Store raw token for one-time retrieval (cleared after user retrieves it)
        token_model.token_metadata = {
            **(token_model.token_metadata or {}),
            "_pending_token": raw_token,
        }
        db.commit()

        logger.info(
            "btcpay_capability_token_created",
            invoice_id=invoice_id,
            token_id=token_model.id,
            tier="premium",
        )

        return {
            "status": "success",
            "invoice_id": invoice_id,
            "token_created": True,
        }

    except Exception as e:
        logger.error(
            "btcpay_webhook_error",
            invoice_id=invoice_id,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        db.close()


@router.get("/payment-token")
async def get_payment_token(invoice_id: str):
    """
    Retrieve capability token for a completed payment.

    Called by the frontend after BTCPay redirect.
    Returns the token once and clears it from pending storage.
    """
    if not invoice_id:
        raise HTTPException(status_code=400, detail="invoice_id required")

    db = SessionLocal()
    try:
        from app.models.capability_token import CapabilityToken

        token = (
            db.query(CapabilityToken)
            .filter(
                CapabilityToken.payment_provider == "btcpay",
                CapabilityToken.payment_reference == invoice_id,
            )
            .first()
        )

        if not token:
            return {
                "status": "pending",
                "message": "Payment not yet confirmed. Please wait.",
            }

        metadata = token.token_metadata or {}
        raw_token = metadata.get("_pending_token")

        if not raw_token:
            # Token was already retrieved
            return {
                "status": "already_retrieved",
                "message": "Token was already retrieved.",
            }

        # Clear the pending token (one-time retrieval)
        metadata.pop("_pending_token", None)
        token.token_metadata = metadata
        db.commit()

        logger.info(
            "btcpay_token_retrieved",
            invoice_id=invoice_id,
            token_id=token.id,
        )

        return {
            "status": "success",
            "token": raw_token,
            "tier": token.tier,
            "max_file_size_bytes": token.max_file_size_bytes,
            "max_expiry_days": token.max_expiry_days,
        }

    finally:
        db.close()
