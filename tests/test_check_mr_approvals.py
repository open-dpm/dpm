"""Tests for GitLab MR approval checking (with mocked HTTP)."""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock

from dpm.codeowners import check_mr_approvals as mod


def _response(payload):
    """Build a fake urlopen context manager returning *payload* as JSON."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_api_request_parses_json(mocker):
    mocker.patch("urllib.request.urlopen", return_value=_response({"ok": 1}))
    assert mod._api_request("https://x/api", "tok") == {"ok": 1}


def test_fetch_approver_usernames(mocker):
    payload = {
        "approved_by": [
            {"user": {"username": "alice"}},
            {"user": {"username": "bob"}},
            {"user": None},
        ]
    }
    mocker.patch("urllib.request.urlopen", return_value=_response(payload))
    names = mod.fetch_mr_approver_usernames("https://x/api", "1", "2", "tok")
    assert names == {"alice", "bob"}


def test_fetch_group_members_paginates(mocker):
    page1 = [{"username": f"u{i}"} for i in range(100)]
    page2 = [{"username": f"u{i}"} for i in range(100, 150)]
    urlopen = mocker.patch(
        "urllib.request.urlopen", side_effect=[_response(page1), _response(page2)]
    )
    members = mod.fetch_group_members("https://x/api", "team", "tok", {})
    assert len(members) == 150
    assert urlopen.call_count == 2


def test_fetch_group_members_handles_http_error(mocker):
    err = urllib.error.HTTPError("url", 500, "err", None, None)
    mocker.patch("urllib.request.urlopen", side_effect=err)
    cache: dict[str, set[str]] = {}
    members = mod.fetch_group_members("https://x/api", "team", "tok", cache)
    assert members == set()
    assert cache["team"] == set()


def test_fetch_group_members_uses_cache(mocker):
    urlopen = mocker.patch(
        "urllib.request.urlopen", return_value=_response([{"username": "a"}])
    )
    cache = {"team": {"cached"}}
    members = mod.fetch_group_members("https://x/api", "team", "tok", cache)
    assert members == {"cached"}
    urlopen.assert_not_called()


def test_build_group_member_index_skips_direct_approvers(mocker):
    urlopen = mocker.patch(
        "urllib.request.urlopen", return_value=_response([{"username": "m"}])
    )
    index = mod.build_group_member_index(
        {"alice", "team"}, {"alice"}, "https://x/api", "tok"
    )
    assert "team" in index
    assert urlopen.call_count == 1


def test_main_no_changed_files(repo_root, mocker):
    mocker.patch.object(mod, "get_changed_files", return_value=[])
    rc = mod.main(["--approved-users", "x", "--repo-root", str(repo_root)])
    assert rc == 0


def test_main_dry_run_pass(repo_root, mocker):
    mocker.patch.object(
        mod, "get_changed_files", return_value=["examples/aviation/flights/sla.yml"]
    )
    rc = mod.main(
        ["--approved-users", "platform-team", "--repo-root", str(repo_root)]
    )
    assert rc == 0


def test_main_dry_run_missing_approval(repo_root, mocker):
    mocker.patch.object(
        mod, "get_changed_files", return_value=["examples/aviation/flights/sla.yml"]
    )
    rc = mod.main(["--approved-users", "", "--repo-root", str(repo_root)])
    assert rc == 1
