"""Revoke a creator bearer token without storing or logging its raw value."""

from __future__ import annotations

import argparse
import getpass
import hashlib

from backend.database import get_database


def revoke_token(raw_token: str) -> bool:
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return get_database().creators.revoke_token(token_hash)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    raw = getpass.getpass("Creator token: ")
    print("revoked" if revoke_token(raw) else "token not found or already revoked")


if __name__ == "__main__":
    main()
