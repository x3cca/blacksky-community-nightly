#!/usr/bin/env python3
"""Apply the deterministic Blacksky Nightly overlay to a clean upstream tree."""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path


APP_NAME = "Blacksky Nightly"
APPLICATION_ID = "community.blacksky.app.nightly"
APK_NAME = "blacksky-nightly-universal.apk"
START_COLOR = (0x16, 0x0A, 0x2B)
END_COLOR = (0x07, 0x2A, 0x4A)
LEGACY_SOURCE = Path("assets/app-icons/android_icon_default_next.png")
LEGACY_NIGHTLY = Path("assets/app-icons/android_icon_nightly.png")
ADAPTIVE_FOREGROUND = Path("assets/icon-android-foreground.png")
ADAPTIVE_MONOCHROME = Path("assets/icon-android-monochrome.png")
ADAPTIVE_BACKGROUND = Path("assets/icon-android-background-nightly.png")


class BrandingError(RuntimeError):
    pass


def _read(path: Path) -> str:
    if not path.is_file():
        raise BrandingError(f"required file is missing: {path}")
    return path.read_text(encoding="utf-8")


def _write_if_changed(path: Path, content: str | bytes) -> None:
    desired = content.encode("utf-8") if isinstance(content, str) else content
    existing = path.read_bytes() if path.exists() else None
    if existing != desired:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(desired)


def _replace_once(text: str, old: str, new: str, description: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise BrandingError(f"expected exactly one {description}; found {count}")
    return text.replace(old, new, 1)


def _paeth(a: int, b: int, c: int) -> int:
    estimate = a + b - c
    distances = (abs(estimate - a), abs(estimate - b), abs(estimate - c))
    if distances[0] <= distances[1] and distances[0] <= distances[2]:
        return a
    if distances[1] <= distances[2]:
        return b
    return c


def read_png(path: Path) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise BrandingError(f"not a PNG: {path}")
    offset = 8
    width = height = bit_depth = color_type = interlace = None
    compressed = bytearray()
    while offset < len(data):
        if offset + 12 > len(data):
            raise BrandingError(f"truncated PNG: {path}")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif chunk_type == b"IDAT":
            compressed.extend(payload)
        elif chunk_type == b"IEND":
            break
    if None in (width, height, bit_depth, color_type, interlace):
        raise BrandingError(f"PNG has no IHDR: {path}")
    if bit_depth != 8 or color_type not in (2, 6) or interlace != 0:
        raise BrandingError(f"expected a non-interlaced 8-bit RGB/RGBA PNG: {path}")

    bytes_per_pixel = 3 if color_type == 2 else 4
    stride = width * bytes_per_pixel
    raw = zlib.decompress(bytes(compressed))
    if len(raw) != height * (stride + 1):
        raise BrandingError(f"unexpected decompressed PNG size: {path}")
    rows: list[bytearray] = []
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        encoded = raw[cursor : cursor + stride]
        cursor += stride
        prior = rows[-1] if rows else bytearray(stride)
        row = bytearray(stride)
        for index, value in enumerate(encoded):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = prior[index]
            upper_left = (
                prior[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            )
            if filter_type == 0:
                decoded = value
            elif filter_type == 1:
                decoded = value + left
            elif filter_type == 2:
                decoded = value + up
            elif filter_type == 3:
                decoded = value + ((left + up) // 2)
            elif filter_type == 4:
                decoded = value + _paeth(left, up, upper_left)
            else:
                raise BrandingError(f"unsupported PNG filter {filter_type}: {path}")
            row[index] = decoded & 0xFF
        rows.append(row)

    pixels: list[tuple[int, int, int, int]] = []
    for row in rows:
        for index in range(0, stride, bytes_per_pixel):
            red, green, blue = row[index : index + 3]
            alpha = row[index + 3] if bytes_per_pixel == 4 else 255
            pixels.append((red, green, blue, alpha))
    return width, height, pixels


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(chunk_type + payload) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", checksum)
    )


def write_png(
    width: int, height: int, pixels: list[tuple[int, int, int, int]]
) -> bytes:
    if len(pixels) != width * height:
        raise BrandingError("pixel count does not match PNG dimensions")
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for pixel in pixels[y * width : (y + 1) * width]:
            rows.extend(pixel)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + _png_chunk(b"IEND", b"")
    )


def gradient_pixels(width: int, height: int) -> list[tuple[int, int, int, int]]:
    denominator = max(1, width + height - 2)
    pixels: list[tuple[int, int, int, int]] = []
    for y in range(height):
        for x in range(width):
            numerator = x + y
            channels = tuple(
                (start * (denominator - numerator) + end * numerator + denominator // 2)
                // denominator
                for start, end in zip(START_COLOR, END_COLOR)
            )
            pixels.append((channels[0], channels[1], channels[2], 255))
    return pixels


def _nightly_legacy_pixels(
    width: int,
    height: int,
    source: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    gradient = gradient_pixels(width, height)
    output: list[tuple[int, int, int, int]] = []
    glyph_pixels = 0
    threshold = 48
    for source_pixel, gradient_pixel in zip(source, gradient):
        red, green, blue, alpha = source_pixel
        luminance = max(red, green, blue)
        coverage = max(
            0,
            min(255, ((luminance - threshold) * 255) // (255 - threshold)),
        )
        if coverage > 128 and alpha:
            glyph_pixels += 1
        channels = tuple(
            (channel * (255 - coverage) + 255 * coverage + 127) // 255
            for channel in gradient_pixel[:3]
        )
        output.append((channels[0], channels[1], channels[2], alpha))
    if glyph_pixels < max(100, (width * height) // 100):
        raise BrandingError("could not recover the Blacksky glyph from the legacy icon")
    return output


def update_icons(worktree: Path) -> dict[str, str]:
    legacy_source = worktree / LEGACY_SOURCE
    foreground = worktree / ADAPTIVE_FOREGROUND
    monochrome = worktree / ADAPTIVE_MONOCHROME
    for path in (legacy_source, foreground, monochrome):
        if not path.is_file():
            raise BrandingError(f"required icon source is missing: {path}")

    foreground_width, foreground_height, _ = read_png(foreground)
    legacy_width, legacy_height, legacy_pixels = read_png(legacy_source)
    if (foreground_width, foreground_height) != (legacy_width, legacy_height):
        raise BrandingError("legacy and adaptive icon sources must have matching dimensions")
    _write_if_changed(
        worktree / ADAPTIVE_BACKGROUND,
        write_png(
            foreground_width,
            foreground_height,
            gradient_pixels(foreground_width, foreground_height),
        ),
    )
    _write_if_changed(
        worktree / LEGACY_NIGHTLY,
        write_png(
            legacy_width,
            legacy_height,
            _nightly_legacy_pixels(legacy_width, legacy_height, legacy_pixels),
        ),
    )
    return {
        "adaptiveForegroundSha256": hashlib.sha256(foreground.read_bytes()).hexdigest(),
        "adaptiveMonochromeSha256": hashlib.sha256(monochrome.read_bytes()).hexdigest(),
    }


def update_app_config(worktree: Path, version_code: int) -> None:
    path = worktree / "app.config.js"
    text = _read(path)
    replacements = (
        ("      name: 'Blacksky',", "      name: 'Blacksky Nightly',", "app name"),
        (
            "        icon: './assets/app-icons/android_icon_default_next.png',",
            "        icon: './assets/app-icons/android_icon_nightly.png',",
            "Android legacy icon",
        ),
        (
            "          backgroundColor: '#000000',",
            "          backgroundImage: './assets/icon-android-background-nightly.png',",
            "adaptive icon background",
        ),
        (
            "        package: 'community.blacksky.app',",
            f"        package: '{APPLICATION_ID}',\n        versionCode: {version_code},",
            "Android package",
        ),
        ("        enabled: true,", "        enabled: false,", "OTA updates flag"),
    )
    for old, new, description in replacements:
        text = _replace_once(text, old, new, description)
    _write_if_changed(path, text)


def update_package_version(worktree: Path, version_name: str) -> None:
    path = worktree / "package.json"
    text = _read(path)
    parsed = json.loads(text)
    current = parsed.get("version")
    if current == version_name:
        return
    rewritten, count = re.subn(
        r'(?m)^(  "version": )"[^"]+",$',
        rf'\g<1>"{version_name}",',
        text,
    )
    if count != 1:
        raise BrandingError(f"expected one package version; found {count}")
    json.loads(rewritten)
    _write_if_changed(path, rewritten)


def update_google_services_example(worktree: Path) -> None:
    path = worktree / "google-services.json.example"
    text = _read(path)
    parsed = json.loads(text)
    clients = parsed.get("client", [])
    packages = [
        client.get("client_info", {})
        .get("android_client_info", {})
        .get("package_name")
        for client in clients
    ]
    if packages == [APPLICATION_ID]:
        return
    if len(packages) != 1 or not packages[0]:
        raise BrandingError(f"expected one Google Services package; found {packages}")
    rewritten, count = re.subn(
        r'("package_name"\s*:\s*)"[^"]+"',
        rf'\g<1>"{APPLICATION_ID}"',
        text,
    )
    if count != 1:
        raise BrandingError(f"expected one Google Services package string; found {count}")
    json.loads(rewritten)
    _write_if_changed(path, rewritten)


def write_metadata(
    worktree: Path,
    version_name: str,
    version_code: int,
    repository: str,
    upstream_commit: str,
    cert_sha256: str,
    icon_hashes: dict[str, str],
) -> None:
    metadata = {
        "schemaVersion": 1,
        "branding": APP_NAME,
        "applicationId": APPLICATION_ID,
        "releaseRepository": repository,
        "releaseAsset": APK_NAME,
        "signingCertificateSha256": cert_sha256.lower(),
        "upstreamCommit": upstream_commit.lower(),
        "versionCode": version_code,
        "versionName": version_name,
        "otaUpdatesEnabled": False,
        "iconGradient": {"start": "#160A2B", "end": "#072A4A"},
        **icon_hashes,
    }
    _write_if_changed(
        worktree / "NIGHTLY_BUILD_METADATA.json",
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
    )


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
    if not (worktree / ".git").exists():
        raise BrandingError(f"not a Git worktree: {worktree}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise BrandingError("repository must be owner/repository")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", args.upstream_commit):
        raise BrandingError("upstream commit must be a full Git object ID")
    cert_sha256 = args.cert_sha256.replace(":", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", cert_sha256):
        raise BrandingError("certificate fingerprint must be SHA-256")
    if not (0 < args.version_code <= 2_100_000_000):
        raise BrandingError("version code is outside Android's supported range")
    if "-nightly." not in args.version_name:
        raise BrandingError("version name does not contain a nightly suffix")

    update_package_version(worktree, args.version_name)
    update_app_config(worktree, args.version_code)
    update_google_services_example(worktree)
    icon_hashes = update_icons(worktree)
    write_metadata(
        worktree,
        args.version_name,
        args.version_code,
        args.repository,
        args.upstream_commit,
        cert_sha256,
        icon_hashes,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrandingError as error:
        print(f"branding error: {error}", file=sys.stderr)
        raise SystemExit(1)
