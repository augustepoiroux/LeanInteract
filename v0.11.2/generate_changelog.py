#!/usr/bin/env python3
"""
Update the changelog from GitHub releases.
This script fetches release information from the GitHub API and updates the changelog file.
"""

import os
import re
import sys
from datetime import datetime

import mdformat
import requests

# Configuration
REPO_OWNER = "augustepoiroux"
REPO_NAME = "LeanInteract"
CHANGELOG_PATH = "docs/changelog.md"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


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


def adjust_headers_in_body(body):
    """Adjust header levels in release body to avoid conflicts with release header"""
    if not body:
        return body

    # Find the largest header level in the body (smallest number of #)
    header_pattern = re.compile(r"^(#{1,6})\s", re.MULTILINE)
    headers = header_pattern.findall(body)

    if not headers:
        return body

    # Find the minimum header level (e.g., if we have ## and ###, min is 2)
    min_level = min(len(h) for h in headers)

    # We want to offset headers so the minimum becomes ### (level 3)
    # since our release header is ## (level 2)
    offset = 3 - min_level

    if offset <= 0:
        return body

    # Add the offset to all headers
    def replace_header(match):
        current_hashes = match.group(1)
        new_level = len(current_hashes) + offset
        # Cap at 6 (maximum markdown header level)
        new_level = min(new_level, 6)
        return "#" * new_level + " "

    return header_pattern.sub(replace_header, body)


def format_links_in_body(body):
    """Surround standalone URLs with < > to make them autolinks"""
    if not body:
        return body

    # Pattern to find URLs that are not already in markdown link format [text](url)
    # This matches http/https URLs that are not preceded by ](
    url_pattern = re.compile(r"(?<!\]\()(https?://[^\s\)]+)(?!\))")

    return url_pattern.sub(r"<\1>", body)


def format_release(release):
    """Format a release for the changelog"""
    tag = release["tag_name"]
    name = release.get("name") or tag
    body = release["body"].strip()
    published_at = format_date(release["published_at"])

    # If the name is just the tag, make it more presentable
    if name == tag:
        name = tag

    # Adjust headers and format links in the body
    body = adjust_headers_in_body(body)
    body = format_links_in_body(body)

    return f"\n\n## {name} ({published_at})\n\n{body}\n"


def generate_changelog(releases):
    """Generate new changelog content with all releases"""
    header = "# Changelog\n\nThis page documents the notable changes to LeanInteract."

    content = header
    for release in releases:
        content += format_release(release)

    content += "## Pre-release Development\n\n"
    content += f"For development history prior to the first release, please see the [GitHub commit history](https://github.com/{REPO_OWNER}/{REPO_NAME}/commits/main)."

    content = mdformat.text(content, extensions={"mkdocs"})

    # add header content for mkdocs
    content = "---\nhide:\n  - navigation\n---\n\n" + content

    with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    releases = fetch_releases()
    # Sort releases by published date (newest first)
    releases.sort(key=lambda r: r["published_at"], reverse=True)
    generate_changelog(releases)


if __name__ == "__main__":
    main()
