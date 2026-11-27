"""Prepare a versioned download and its manifest for publication on main."""

import argparse
import json
from pathlib import Path
import re
import shutil

from winlock_core import version_key


MANIFEST = Path("version.json")


def pending_version():
    source = Path("main.py").read_text(encoding="utf-8")
    app_version = re.search(r'^LOCAL_VERSION = "([^"]+)"$', source, re.MULTILINE)
    if app_version is None:
        raise ValueError("Could not read LOCAL_VERSION from main.py.")
    version = app_version[1]
    source_key = version_key(version)
    readme = Path("README.md").read_text(encoding="utf-8")
    title = re.match(r"# WinLock (\S+)", readme)
    website = Path("website/index.html").read_text(encoding="utf-8")
    badge = re.search(r'id="navVersion"[^>]*>([^<]+)</span>', website)
    versions = {
        "README.md": title[1] if title else None,
        "website/index.html": badge[1] if badge else None,
    }
    for path, source_version in versions.items():
        if source_version != version:
            raise ValueError(f"{path} has version {source_version!r}; expected {version}.")
    published = json.loads(MANIFEST.read_text(encoding="utf-8"))["tag_name"]
    if version == published:
        return None
    if source_key <= version_key(published):
        raise ValueError(f"{version} must be newer than the published version {published}.")
    return version


def prepare(version, repository):
    if version != pending_version():
        raise ValueError(f"{version} is not the pending version on main.")
    executable = Path("dist/WinLock.exe")
    size = executable.stat().st_size
    if not 0 < size <= 100 * 1024**2:
        raise ValueError("WinLock.exe is empty or exceeds GitHub's 100 MiB file limit.")
    destination = Path("downloads") / version / executable.name
    destination.parent.mkdir(parents=True)
    shutil.copyfile(executable, destination)

    manifest = {
        "tag_name": version,
        "download_url": f"https://raw.githubusercontent.com/{repository}/refs/heads/main/{destination.as_posix()}",
        "size": f"{size / 1_000_000:.2f} MB",
    }
    MANIFEST.write_text(json.dumps(manifest, indent="\t") + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pending-version")
    prepare_command = commands.add_parser("prepare")
    prepare_command.add_argument("version")
    prepare_command.add_argument("repository")
    args = parser.parse_args()
    try:
        if args.command == "pending-version":
            version = pending_version()
            if version is not None:
                print(version)
        else:
            prepare(args.version, args.repository)
    except (KeyError, OSError, ValueError) as error:
        parser.exit(1, f"Release validation failed: {error}\n")


if __name__ == "__main__":
    main()
