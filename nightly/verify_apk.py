#!/usr/bin/env python3
"""Verify the signed Blacksky Nightly APK's metadata and signer."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from apply_branding import APK_NAME, APPLICATION_ID, APP_NAME


def run(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}"
        )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--aapt", required=True, type=Path)
    parser.add_argument("--apksigner", required=True, type=Path)
    parser.add_argument("--version-name", required=True)
    parser.add_argument("--version-code", required=True)
    parser.add_argument("--cert-sha256", required=True)
    args = parser.parse_args()

    if args.apk.name != APK_NAME:
        raise RuntimeError(f"unexpected APK filename: {args.apk.name}")
    badging = run([str(args.aapt), "dump", "badging", str(args.apk)])
    package = re.search(
        r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'",
        badging,
        re.MULTILINE,
    )
    if package is None:
        raise RuntimeError("aapt did not report package metadata")
    actual_package, actual_code, actual_name = package.groups()
    if actual_package != APPLICATION_ID:
        raise RuntimeError(f"unexpected application ID: {actual_package}")
    if actual_code != args.version_code:
        raise RuntimeError(f"unexpected version code: {actual_code}")
    if actual_name != args.version_name:
        raise RuntimeError(f"unexpected version name: {actual_name}")
    labels = re.findall(
        r"^application-label(?:-[^:]+)?:'([^']+)'", badging, re.MULTILINE
    )
    if not labels or any(label != APP_NAME for label in labels):
        raise RuntimeError(f"unexpected application labels: {sorted(set(labels))}")

    signer = run(
        [str(args.apksigner), "verify", "--verbose", "--print-certs", str(args.apk)]
    )
    match = re.search(
        r"certificate SHA-256 digest:\s*([0-9a-fA-F:]{64,95})", signer
    )
    if match is None:
        raise RuntimeError("apksigner did not report a SHA-256 certificate digest")
    actual_cert = match.group(1).replace(":", "").lower()
    expected_cert = args.cert_sha256.replace(":", "").lower()
    if actual_cert != expected_cert:
        raise RuntimeError(
            f"signer mismatch: expected {expected_cert}, got {actual_cert}"
        )
    print(
        f"verified {args.apk.name}: {APPLICATION_ID}, {APP_NAME}, "
        f"{args.version_name} ({args.version_code}), signer {actual_cert}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError) as error:
        print(f"APK verification error: {error}", file=sys.stderr)
        raise SystemExit(1)
