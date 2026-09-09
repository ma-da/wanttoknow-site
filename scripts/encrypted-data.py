#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

BACKEND_ROOT = (
    REPO_ROOT
    / "backend"
)

sys.path.insert(
    0,
    str(BACKEND_ROOT),
)


from app.services.crypto import (  # noqa: E402
    decrypt_bytes,
    decrypt_json,
    encrypt_bytes,
)


def read_jsonl(
    path: Path,
):
    with path.open(
        "r",
        encoding="utf-8",
    ) as handle:
        for line_number, line in enumerate(
            handle,
            start=1,
        ):
            line = line.strip()

            if not line:
                continue

            try:
                yield (
                    line_number,
                    json.loads(line),
                )

            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path}: invalid JSON "
                    f"on line {line_number}"
                ) from exc


def command_verify_jsonl(
    args,
) -> None:
    path = Path(
        args.path
    )

    count = 0

    for line_number, envelope in read_jsonl(
        path
    ):
        try:
            decrypt_json(
                envelope,
                expected_purpose=(
                    args.purpose
                ),
            )

        except Exception as exc:
            raise RuntimeError(
                f"Decryption failed on "
                f"line {line_number}"
            ) from exc

        count += 1

    print(
        f"PASS: {count} encrypted "
        f"record(s) verified."
    )


def command_decrypt_jsonl(
    args,
) -> None:
    path = Path(
        args.path
    )

    for _, envelope in read_jsonl(
        path
    ):
        value = decrypt_json(
            envelope,
            expected_purpose=(
                args.purpose
            ),
        )

        print(
            json.dumps(
                value,
                ensure_ascii=False,
            )
        )


def command_encrypt_file(
    args,
) -> None:
    source = Path(
        args.input
    )

    destination = Path(
        args.output
    )

    envelope = encrypt_bytes(
        source.read_bytes(),
        purpose=args.purpose,
    )

    destination.write_text(
        json.dumps(
            envelope,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def command_decrypt_file(
    args,
) -> None:
    source = Path(
        args.input
    )

    destination = Path(
        args.output
    )

    envelope = json.loads(
        source.read_text(
            encoding="utf-8"
        )
    )

    plaintext = decrypt_bytes(
        envelope,
        expected_purpose=args.purpose,
    )

    destination.write_bytes(
        plaintext
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "WantToKnow.info encrypted "
            "data administration utility"
        )
    )

    subparsers = parser.add_subparsers(
        required=True
    )

    verify = subparsers.add_parser(
        "verify-jsonl"
    )

    verify.add_argument(
        "--purpose",
        required=True,
    )

    verify.add_argument(
        "path",
    )

    verify.set_defaults(
        func=command_verify_jsonl
    )

    decrypt_jsonl = (
        subparsers.add_parser(
            "decrypt-jsonl"
        )
    )

    decrypt_jsonl.add_argument(
        "--purpose",
        required=True,
    )

    decrypt_jsonl.add_argument(
        "path",
    )

    decrypt_jsonl.set_defaults(
        func=command_decrypt_jsonl
    )

    encrypt_file = (
        subparsers.add_parser(
            "encrypt-file"
        )
    )

    encrypt_file.add_argument(
        "--purpose",
        required=True,
    )

    encrypt_file.add_argument(
        "input",
    )

    encrypt_file.add_argument(
        "output",
    )

    encrypt_file.set_defaults(
        func=command_encrypt_file
    )

    decrypt_file = (
        subparsers.add_parser(
            "decrypt-file"
        )
    )

    decrypt_file.add_argument(
        "--purpose",
        required=True,
    )

    decrypt_file.add_argument(
        "input",
    )

    decrypt_file.add_argument(
        "output",
    )

    decrypt_file.set_defaults(
        func=command_decrypt_file
    )

    args = parser.parse_args()

    args.func(
        args
    )


if __name__ == "__main__":
    main()