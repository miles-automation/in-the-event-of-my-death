"""Typed domain exceptions for the IEOMD backend.

These replace generic ValueError + string matching in routers,
giving each error case a distinct type that routers can catch directly.
"""


class VaultExistsError(Exception):
    """Raised when attempting to create a vault that already exists."""

    def __init__(self) -> None:
        super().__init__("Vault already exists")


class ETagMismatchError(Exception):
    """Raised when the provided ETag does not match the current vault version."""

    def __init__(
        self, message: str = "ETag mismatch \u2014 vault was modified by another device"
    ) -> None:
        super().__init__(message)


class VaultBlobTooLargeError(Exception):
    """Raised when the vault blob exceeds the size limit."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"Vault blob exceeds {limit} byte limit")
        self.limit = limit
