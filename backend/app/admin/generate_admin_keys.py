from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Mark and Amber WantToKnow admin access keys."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root() / "backend/var/admin-keys",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=repo_root() / "backend/var/admin-auth.json",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output_dir = args.output_dir.expanduser().resolve()
    config_path = args.config.expanduser().resolve()
    key_paths = {
        "Mark": output_dir / "mark.key",
        "Amber": output_dir / "amber.key",
    }

    existing = [path for path in [*key_paths.values(), config_path] if path.exists()]
    if existing and not args.force:
        print("Refusing to overwrite existing auth material:")
        for path in existing:
            print(f"  {path}")
        print("Use --force only if you intentionally want to replace the access keys.")
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    for name, path in key_paths.items():
        secret = "wtk_" + secrets.token_urlsafe(32)
        write_private(path, secret + "\n")
        entries.append(
            {
                "name": name,
                "sha256": hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            }
        )

    config = {"version": 1, "keys": entries}
    write_private(config_path, json.dumps(config, indent=2) + "\n")

    print("Generated WantToKnow admin access material:")
    print(f"  Mark key:   {key_paths['Mark']}")
    print(f"  Amber key:  {key_paths['Amber']}")
    print(f"  Hash config:{config_path}")
    print()
    print("The config contains only SHA-256 hashes. Keep the .key files private.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
