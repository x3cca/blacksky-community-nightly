#!/usr/bin/env python3
"""Make Expo's generated release variant unsigned and validate native metadata."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from apply_branding import APPLICATION_ID, APP_NAME, BrandingError


MARKER = "// Blacksky Nightly is signed after assembly with the persistent release key."


def configure(build_gradle: Path) -> None:
    if not build_gradle.is_file():
        raise BrandingError(f"generated Gradle file is missing: {build_gradle}")
    text = build_gradle.read_text(encoding="utf-8")
    if MARKER in text:
        return

    lines = text.splitlines(keepends=True)
    release_start = None
    release_end = None
    build_types_depth = None
    depth = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        opens = line.count("{")
        closes = line.count("}")
        if build_types_depth is None and re.fullmatch(r"buildTypes\s*\{", stripped):
            build_types_depth = depth + opens - closes
        elif (
            build_types_depth is not None
            and release_start is None
            and re.fullmatch(r"release\s*\{", stripped)
            and depth == build_types_depth
        ):
            release_start = index
            release_depth = depth + opens - closes
        elif release_start is not None and release_end is None:
            release_depth_after = depth + opens - closes
            if release_depth_after < release_depth:
                release_end = index
                break
        depth += opens - closes

    if release_start is None or release_end is None:
        raise BrandingError("could not identify the generated release build type")
    candidates = [
        index
        for index in range(release_start + 1, release_end)
        if re.fullmatch(r"\s*signingConfig\s+signingConfigs\.debug\s*", lines[index])
    ]
    if len(candidates) != 1:
        raise BrandingError(
            f"expected one debug release signing configuration; found {len(candidates)}"
        )
    index = candidates[0]
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
    lines[index] = indent + MARKER + newline
    build_gradle.write_text("".join(lines), encoding="utf-8", newline="")


def validate_native(
    android_dir: Path, version_name: str, version_code: int
) -> None:
    build_gradle = (android_dir / "app/build.gradle").read_text(encoding="utf-8")
    required_patterns = (
        (rf"applicationId\s+['\"]{re.escape(APPLICATION_ID)}['\"]", "application ID"),
        (rf"versionCode\s+{version_code}\b", "version code"),
        (rf"versionName\s+['\"]{re.escape(version_name)}['\"]", "version name"),
    )
    for pattern, description in required_patterns:
        if re.search(pattern, build_gradle) is None:
            raise BrandingError(f"generated Android {description} is wrong")
    if build_gradle.count("signingConfig signingConfigs.debug") != 1:
        raise BrandingError("generated signing configuration count is unexpected")
    if MARKER not in build_gradle:
        raise BrandingError("nightly unsigned-release marker is missing")

    strings = (android_dir / "app/src/main/res/values/strings.xml").read_text(
        encoding="utf-8"
    )
    if f'<string name="app_name">{APP_NAME}</string>' not in strings:
        raise BrandingError("generated Android app label is wrong")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--version-name", required=True)
    parser.add_argument("--version-code", required=True, type=int)
    args = parser.parse_args()
    android_dir = args.worktree.resolve() / "android"
    configure(android_dir / "app/build.gradle")
    validate_native(android_dir, args.version_name, args.version_code)
    print("validated generated Android project and disabled debug release signing")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BrandingError, OSError, ValueError) as error:
        print(f"native Android configuration error: {error}", file=sys.stderr)
        raise SystemExit(1)
