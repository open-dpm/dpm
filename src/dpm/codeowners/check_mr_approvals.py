#!/usr/bin/env python3
"""Verify MR has approval from CODEOWNERS for every touched manifest/platform scope."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dpm.codeowners.codeowners import find_unsatisfied_scopes

REPO_ROOT = Path(__file__).resolve().parent.parent


def get_changed_files(base_ref: str, head_ref: str) -> list[str]:
    """Return files changed between base and head."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _api_request(url: str, token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"JOB-TOKEN": token},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_mr_approver_usernames(
    api_url: str,
    project_id: str,
    mr_iid: str,
    token: str,
) -> set[str]:
    """Fetch usernames who approved the merge request."""
    url = f"{api_url.rstrip('/')}/projects/{project_id}/merge_requests/{mr_iid}/approvals"
    payload = _api_request(url, token)
    usernames: set[str] = set()
    for entry in payload.get("approved_by", []):
        user = entry.get("user") or {}
        username = user.get("username")
        if username:
            usernames.add(username)
    return usernames


def fetch_group_members(
    api_url: str,
    group_handle: str,
    token: str,
    cache: dict[str, set[str]],
) -> set[str]:
    """Fetch GitLab group member usernames (cached)."""
    if group_handle in cache:
        return cache[group_handle]

    encoded = urllib.parse.quote(group_handle, safe="")
    url = (
        f"{api_url.rstrip('/')}/groups/{encoded}/members/all"
        "?per_page=100"
    )
    members: set[str] = set()
    page = 1
    while url:
        paged_url = url if page == 1 else f"{url}&page={page}"
        try:
            request = urllib.request.Request(
                paged_url,
                headers={"JOB-TOKEN": token},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            cache[group_handle] = members
            return members

        if not batch:
            break
        for member in batch:
            username = member.get("username")
            if username:
                members.add(username)
        if len(batch) < 100:
            break
        page += 1

    cache[group_handle] = members
    return members


def build_group_member_index(
    scopes_handles: set[str],
    approved_usernames: set[str],
    api_url: str,
    token: str,
) -> dict[str, set[str]]:
    """Load group memberships for handles that are not direct approver usernames."""
    cache: dict[str, set[str]] = {}
    for handle in scopes_handles:
        if handle in approved_usernames:
            continue
        fetch_group_members(api_url, handle, token, cache)
    return cache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check MR approvals against per-directory CODEOWNERS files.",
    )
    parser.add_argument(
        "--base-ref",
        default=os.getenv("CI_MERGE_REQUEST_DIFF_BASE_SHA", "origin/main"),
        help="Git base ref for changed files (default: origin/main)",
    )
    parser.add_argument(
        "--head-ref",
        default="HEAD",
        help="Git head ref for changed files (default: HEAD)",
    )
    parser.add_argument(
        "--mr-iid",
        default=os.getenv("CI_MERGE_REQUEST_IID"),
        help="Merge request IID (default: CI_MERGE_REQUEST_IID)",
    )
    parser.add_argument(
        "--project-id",
        default=os.getenv("CI_PROJECT_ID"),
        help="GitLab project ID (default: CI_PROJECT_ID)",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("CI_API_V4_URL", "https://gitlab.com/api/v4"),
        help="GitLab API v4 base URL",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("CI_JOB_TOKEN"),
        help="GitLab CI job token (default: CI_JOB_TOKEN)",
    )
    parser.add_argument(
        "--approved-users",
        help="Comma-separated approver usernames (local/CI dry-run without API)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root path",
    )
    args = parser.parse_args(argv)

    changed_files = get_changed_files(args.base_ref, args.head_ref)
    if not changed_files:
        print("No changed files — CODEOWNERS approval check skipped.")
        return 0

    from dpm.codeowners.codeowners import collect_required_scopes

    scopes = collect_required_scopes(changed_files, args.repo_root)
    if not scopes:
        print("No CODEOWNERS scopes matched changed files — check skipped.")
        return 0

    all_handles: set[str] = set()
    for scope in scopes.values():
        all_handles.update(scope.handles)

    if args.approved_users is not None:
        approved = {u.strip() for u in args.approved_users.split(",") if u.strip()}
        group_members: dict[str, set[str]] = {}
    else:
        if not args.mr_iid or not args.project_id or not args.token:
            print(
                "ERROR: CI_MERGE_REQUEST_IID, CI_PROJECT_ID and CI_JOB_TOKEN are required.",
                file=sys.stderr,
            )
            return 1
        approved = fetch_mr_approver_usernames(
            args.api_url, args.project_id, args.mr_iid, args.token
        )
        group_members = build_group_member_index(
            all_handles, approved, args.api_url, args.token
        )

    unsatisfied = find_unsatisfied_scopes(
        changed_files, args.repo_root, approved, group_members
    )
    if not unsatisfied:
        print("CODEOWNERS approval check passed.")
        for scope in scopes.values():
            rel = scope.path.relative_to(args.repo_root)
            print(f"  OK {rel}: {', '.join(f'@{h}' for h in sorted(scope.handles))}")
        return 0

    print("CODEOWNERS approval check FAILED.", file=sys.stderr)
    print(f"Approved users: {', '.join(sorted(approved)) or '(none)'}", file=sys.stderr)
    for scope in unsatisfied:
        rel = scope.path.relative_to(args.repo_root)
        handles = ", ".join(f"@{h}" for h in sorted(scope.handles))
        print(
            f"  MISSING approval for {rel} (need one of: {handles})",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
