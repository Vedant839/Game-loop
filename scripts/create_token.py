"""Create a one-time-display creator bearer token."""

from __future__ import annotations

import argparse
import hashlib
import secrets

from backend.database import get_database


def create_token(creator_id: str, label: str = "") -> str:
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    get_database().creators.save_token(token_hash, creator_id, label)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creator-id", default="default_client")
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    print(create_token(args.creator_id, args.label))


if __name__ == "__main__":
    main()
