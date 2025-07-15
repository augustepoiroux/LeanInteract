#!/usr/bin/env python3
"""
Update the changelog from GitHub releases.
This script fetches release information from the GitHub API and updates the changelog file.
"""

import argparse
import os
import re
import sys
from datetime import datetime

import requests

# Configuration
REPO_OWNER = "augustepoiroux"
REPO_NAME = "LeanInteract"
CHANGELOG_PATH = "docs/changelog.md"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # Set this environment variable if you're hitting rate limits


def format_date(date_string):
    """Format the date as Month Day, Year"""
    date_obj = datetime.fromisoformat(date_string.replace("Z", "+00:00"))
    return date_obj.strftime("%B %d, %Y")


def fetch_releases():
    """Fetch releases from GitHub API"""
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases"
    response = requests.get(url, headers=headers, timeout=30)  # 30 seconds timeout

    if response.status_code != 200:
        print(f"Failed to fetch releases: {response.status_code}")
        print(response.text)
        sys.exit(1)

    return response.json()


def format_release(release):
    """Format a release for the changelog"""
    tag = release["tag_name"]
    name = release.get("name") or tag
    body = release["body"].strip()
    published_at = format_date(release["published_at"])

    # If the name is just the tag, make it more presentable
    if name == tag:
        name = tag

    return f"\n\n## {name} ({published_at})\n\n{body}\n"


def update_changelog(releases):
    """Update the changelog file with the releases"""
    # Create changelog if it doesn't exist
    if not os.path.exists(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
            f.write("# Changelog\n\nThis page documents the notable changes to LeanInteract.\n\n")

    # Read current changelog content
    with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract header and existing releases
    header_match = re.match(r"(# Changelog\s+.*?)\s*##", content, re.DOTALL)
    if header_match:
        header = header_match.group(1)
    else:
        header = "# Changelog\n\nThis page documents the notable changes to LeanInteract.\n\n"

    # Check if we're only updating a single release
    if len(releases) == 1:
        # For a single release, insert it after the header
        new_release = format_release(releases[0])

        # Check if this release already exists in the changelog
        release_tag = releases[0]["tag_name"]
        if re.search(rf"## .*{re.escape(release_tag)}.*?\(", content):
            print(f"Release {release_tag} already exists in the changelog. Skipping update.")
            return

        # Insert the new release after the header
        new_content = re.sub(r"(# Changelog\s+.*?)(\s*##)", f"\\1{new_release}\\2", content, count=1, flags=re.DOTALL)

        # If the pattern didn't match, append to header
        if new_content == content:
            new_content = header + new_release + content[len(header) :]
    else:
        # Generate new changelog content with all releases
        new_content = header
        for release in releases:
            new_content += format_release(release)

        # Add a note about pre-release development if it doesn't exist in content
        if "## Pre-release Development" not in content:
            new_content += "## Pre-release Development\n\n"
            new_content += f"For development history prior to the first release, please see the [GitHub commit history](https://github.com/{REPO_OWNER}/{REPO_NAME}/commits/main)."
        else:
            # Extract and add the pre-release section
            pre_release_match = re.search(r"(## Pre-release Development[\s\S]*$)", content)
            if pre_release_match:
                new_content += pre_release_match.group(1)

    # Write updated changelog
    with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"Updated {CHANGELOG_PATH} with {len(releases)} releases.")


def fetch_release_by_tag(tag_name):
    """Fetch a specific release by its tag name"""
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags/{tag_name}"
    response = requests.get(url, headers=headers, timeout=30)  # 30 seconds timeout

    if response.status_code != 200:
        print(f"Failed to fetch release with tag '{tag_name}': {response.status_code}")
        print(response.text)
        sys.exit(1)

    return response.json()


def main():
    parser = argparse.ArgumentParser(description="Update the changelog with GitHub release information")
    parser.add_argument("--release-tag", type=str, help="Update the changelog with only this specific release tag")
    args = parser.parse_args()

    if args.release_tag:
        # Get a specific release by tag name
        release = fetch_release_by_tag(args.release_tag)
        releases = [release]
    else:
        # Get all releases
        releases = fetch_releases()
        if not releases:
            print("No releases found.")
            return
        # Sort releases by published date (newest first)
        releases.sort(key=lambda r: r["published_at"], reverse=True)

    update_changelog(releases)


if __name__ == "__main__":
    main()
