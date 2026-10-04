"""Durable runtime errors."""


class ReadAfterWrite(RuntimeError):
    def __init__(self, method: str) -> None:
        super().__init__(f"Tx.{method}() cannot read tables after the first table write")


class StorageRejected(RuntimeError):
    """A storage batch was rejected before any durable effect was committed."""
