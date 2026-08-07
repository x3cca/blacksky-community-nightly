#!/usr/bin/env python3
"""Validate every invariant produced by the Blacksky Nightly overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from apply_branding import (
    ADAPTIVE_BACKGROUND,
    ADAPTIVE_FOREGROUND,
    ADAPTIVE_MONOCHROME,
    APK_NAME,
    APPLICATION_ID,
    APP_NAME,
    END_COLOR,
    LEGACY_NIGHTLY,
    START_COLOR,
    BrandingError,
    gradient_pixels,
    read_png,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BrandingError(message)


def _read(path: Path) -> str:
    _require(path.is_file(), f"required file is missing: {path}")
    return path.read_text(encoding="utf-8")


def expected_metadata(
    worktree: Path,
    version_name: str,
    version_code: int,
    repository: str,
    upstream_commit: str,
    cert_sha256: str,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "branding": APP_NAME,
        "applicationId": APPLICATION_ID,
        "releaseRepository": repository,
        "releaseAsset": APK_NAME,
        "signingCertificateSha256": cert_sha256.replace(":", "").lower(),
        "upstreamCommit": upstream_commit.lower(),
        "versionCode": version_code,
        "versionName": version_name,
        "otaUpdatesEnabled": False,
        "iconGradient": {"start": "#160A2B", "end": "#072A4A"},
        "adaptiveForegroundSha256": hashlib.sha256(
            (worktree / ADAPTIVE_FOREGROUND).read_bytes()
        ).hexdigest(),
        "adaptiveMonochromeSha256": hashlib.sha256(
            (worktree / ADAPTIVE_MONOCHROME).read_bytes()
        ).hexdigest(),
    }


def validate_config(worktree: Path, version_name: str, version_code: int) -> None:
    config = _read(worktree / "app.config.js")
    _require("      name: 'Blacksky Nightly'," in config, "nightly app name is missing")
    _require(
        f"        package: '{APPLICATION_ID}'," in config,
        "nightly application ID is missing",
    )
    _require(
        "        package: 'community.blacksky.app'," not in config,
        "official application ID is still configured",
    )
    _require(
        f"        versionCode: {version_code}," in config,
        "nightly version code is missing",
    )
    _require(
        "        icon: './assets/app-icons/android_icon_nightly.png'," in config,
        "nightly legacy icon is not configured",
    )
    _require(
        "          backgroundImage: './assets/icon-android-background-nightly.png',"
        in config,
        "nightly adaptive background is not configured",
    )
    _require("          backgroundColor: '#000000'," not in config, "solid icon background remains")
    update_blocks = re.findall(r"(?ms)^      updates: \{(.*?)^      \},", config)
    _require(len(update_blocks) == 1, "could not identify exactly one Expo updates block")
    _require("enabled: false" in update_blocks[0], "OTA updates are not disabled")

    package = json.loads(_read(worktree / "package.json"))
    _require(package.get("version") == version_name, "package version is not branded")
    google_services = json.loads(_read(worktree / "google-services.json.example"))
    packages = [
        client.get("client_info", {})
        .get("android_client_info", {})
        .get("package_name")
        for client in google_services.get("client", [])
    ]
    _require(packages == [APPLICATION_ID], f"unexpected Google Services packages: {packages}")


def validate_icons(worktree: Path) -> None:
    background_path = worktree / ADAPTIVE_BACKGROUND
    width, height, background = read_png(background_path)
    _require((width, height) == (1024, 1024), "adaptive gradient has unexpected dimensions")
    _require(
        background == gradient_pixels(width, height),
        "adaptive icon gradient is not deterministic",
    )
    _require(background[0][:3] == START_COLOR, "gradient start color is wrong")
    _require(background[-1][:3] == END_COLOR, "gradient end color is wrong")

    legacy_width, legacy_height, legacy = read_png(worktree / LEGACY_NIGHTLY)
    _require(
        (legacy_width, legacy_height) == (width, height),
        "legacy nightly icon has unexpected dimensions",
    )
    _require(legacy[0] == (*START_COLOR, 255), "legacy icon does not start with gradient")
    _require(legacy[-1] == (*END_COLOR, 255), "legacy icon does not end with gradient")
    white_pixels = sum(1 for red, green, blue, alpha in legacy if alpha and min(red, green, blue) > 230)
    _require(white_pixels > (width * height) // 100, "Blacksky glyph is missing from legacy icon")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--version-name", required=True)
    parser.add_argument("--version-code", required=True, type=int)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--upstream-commit", required=True)
    parser.add_argument("--cert-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    worktree = args.worktree.resolve()
    validate_config(worktree, args.version_name, args.version_code)
    validate_icons(worktree)
    metadata = json.loads(_read(worktree / "NIGHTLY_BUILD_METADATA.json"))
    _require(
        metadata
        == expected_metadata(
            worktree,
            args.version_name,
            args.version_code,
            args.repository,
            args.upstream_commit,
            args.cert_sha256,
        ),
        "NIGHTLY_BUILD_METADATA.json does not match build inputs",
    )
    print(
        f"validated {APP_NAME} {args.version_name} ({args.version_code}) "
        f"for {args.repository}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrandingError as error:
        print(f"branding validation error: {error}", file=sys.stderr)
        raise SystemExit(1)
