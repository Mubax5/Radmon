"""Keep encoded password/PIN storage unambiguously different from plaintext.

PBKDF2 salt/digest bytes are random. A short numeric PIN can, by chance, occur
as a substring of the hexadecimal encoding even though the PIN is not stored.
Rejecting that rare encoding removes ambiguity without changing the KDF,
verification format, or compatibility with existing hashes.
"""
from __future__ import annotations


def apply() -> None:
    from .security import SecurityStore

    original_hash_secret = SecurityStore._hash_secret

    @classmethod
    def hash_secret(cls, value: str) -> str:
        while True:
            encoded = original_hash_secret(value)
            if value not in encoded:
                return encoded

    SecurityStore._hash_secret = hash_secret
