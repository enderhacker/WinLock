"""Check release versions and write the manifest from GitHub's published asset."""

import argparse
import json
from pathlib import Path
import re
import sys

from winlock_core import version_key


MANIFEST = Path("version.json")


def check_source(tag):
    from main import LOCAL_VERSION

    readme = Path("README.md").read_text(encoding="utf-8")
    title = re.match(r"# WinLock (\S+)", readme)
    website = Path("website/index.html").read_text(encoding="utf-8")
    badge = re.search(r'id="navVersion"[^>]*>([^<]+)</span>', website)
    versions = {
        "main.py": LOCAL_VERSION,
        "README.md": title[1] if title else None,
        "website/index.html": badge[1] if badge else None,
    }
    for path, source_version in versions.items():
        if source_version != tag:
            raise ValueError(f"{path} has version {source_version!r}; expected {tag}.")


def check_order(tag, latest):
    published = json.loads(MANIFEST.read_text(encoding="utf-8"))["tag_name"]
    for version in (published, latest):
        if tag != version and version_key(tag) <= version_key(version):
            raise ValueError(f"{tag} must be newer than {version}.")


def write_manifest(tag, release):
    if release["tag_name"] != tag or release["draft"] or release["prerelease"]:
        raise ValueError(f"{tag} is not a published stable release.")
    asset = next((asset for asset in release["assets"] if asset["name"] == "WinLock.exe"), None)
    if not asset or asset["state"] != "uploaded" or asset["size"] <= 0:
        raise ValueError(f"{tag} has no uploaded WinLock.exe.")
    manifest = {
        "tag_name": tag,
        "download_url": asset["browser_download_url"],
        "size": f"{asset['size'] / 1_000_000:.2f} MB",
    }
    MANIFEST.write_text(json.dumps(manifest, indent="\t") + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("check-source", "check-order", "write-manifest"):
        commands.add_parser(command).add_argument("tag")
    commands.choices["check-order"].add_argument("latest")
    args = parser.parse_args()
    try:
        version_key(args.tag)
        if args.command == "check-source":
            check_source(args.tag)
        elif args.command == "check-order":
            check_order(args.tag, args.latest)
        else:
            write_manifest(args.tag, json.load(sys.stdin))
    except (KeyError, ValueError) as error:
        parser.exit(1, f"Release validation failed: {error}\n")


if __name__ == "__main__":
    main()
