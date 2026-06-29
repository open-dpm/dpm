#!/usr/bin/env python3
"""DPM CLI — Data Product Manifest toolkit."""

from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dpm",
        description="Data Product Manifest (DPM) validation and governance toolkit",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="Validate manifest.yaml structure")
    p_validate.add_argument("path", nargs="?", help="Path to manifest.yaml")
    p_validate.add_argument("--all", action="store_true", help="Validate all manifests in examples/")
    p_validate.add_argument("--base-path", default=".", help="Base path for examples directory")
    p_validate.add_argument("--json-output", metavar="FILE", help="Write JSON report to FILE")

    p_rules = sub.add_parser("validate-rules", help="Validate quality_rules.yml files")
    p_rules.add_argument("path", nargs="?", help="Path to quality_rules.yml")
    p_rules.add_argument("--all", action="store_true", help="Validate all quality rules")
    p_rules.add_argument("--base-path", default=".")

    p_gov = sub.add_parser("governance", help="Validate governance requirements")
    p_gov.add_argument("path", nargs="?", help="Path to manifest.yaml")
    p_gov.add_argument("--all", action="store_true")
    p_gov.add_argument("--base-path", default=".")

    p_break = sub.add_parser("breaking-changes", help="Detect breaking schema changes")
    p_break.add_argument("--base-ref", default="origin/main")
    p_break.add_argument("--head-ref", default="HEAD")
    p_break.add_argument("--output", help="Output JSON report path")

    p_version = sub.add_parser("suggest-version", help="Suggest semver bump")
    p_version.add_argument("--breaking-changes-file", required=True)
    p_version.add_argument("--output", help="Output JSON path")

    p_conf = sub.add_parser(
        "validate-conformance", help="Validate product conformance to canonical entities"
    )
    p_conf.add_argument("path", nargs="?", help="Path to a product manifest.yaml")
    p_conf.add_argument("--all", action="store_true", help="Validate all manifests")
    p_conf.add_argument("--base-path", default=".", help="Base path for product manifests")
    p_conf.add_argument(
        "--registry-path", required=True, help="Path to the canonical registry"
    )
    p_conf.add_argument("--output", help="Output JSON report path")

    p_impact = sub.add_parser(
        "conformance-impact", help="List products conforming to a canonical entity version"
    )
    p_impact.add_argument("--entity", required=True, help="Canonical entity name")
    p_impact.add_argument("--version", required=True, help="Major version (e.g. 1)")
    p_impact.add_argument("--base-path", default=".", help="Base path to scan")
    p_impact.add_argument("--output", help="Output JSON report path")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        from dpm.validators import validate_manifest as vm

        sys.argv = ["validate_manifest"]
        if args.all:
            sys.argv += ["--all", "--base-path", args.base_path]
        elif args.path:
            sys.argv += [args.path]
        else:
            parser.error("validate requires path or --all")
        if args.json_output:
            sys.argv += ["--json-output", args.json_output]
        vm.main()

    elif args.command == "validate-rules":
        from dpm.validators import validate_quality_rules as vqr

        sys.argv = ["validate_quality_rules"]
        if args.all:
            sys.argv += ["--all", "--base-path", args.base_path]
        elif args.path:
            sys.argv += [args.path]
        else:
            parser.error("validate-rules requires path or --all")
        vqr.main()

    elif args.command == "governance":
        from dpm.validators import validate_governance as vg

        sys.argv = ["validate_governance"]
        if args.all:
            sys.argv += ["--all", "--base-path", args.base_path]
        elif args.path:
            sys.argv += [args.path]
        else:
            parser.error("governance requires path or --all")
        vg.main()

    elif args.command == "breaking-changes":
        from dpm.validators import detect_breaking_changes as dbc

        sys.argv = [
            "detect_breaking_changes",
            "--base-ref", args.base_ref,
            "--head-ref", args.head_ref,
        ]
        if args.output:
            sys.argv += ["--output", args.output]
        dbc.main()

    elif args.command == "suggest-version":
        from dpm.validators import suggest_version as sv

        sys.argv = [
            "suggest_version",
            "--breaking-changes-file", args.breaking_changes_file,
        ]
        if args.output:
            sys.argv += ["--output", args.output]
        sv.main()

    elif args.command == "validate-conformance":
        from dpm.validators import validate_conformance as vc

        sys.argv = ["validate_conformance", "--registry-path", args.registry_path]
        if args.all:
            sys.argv += ["--all", "--base-path", args.base_path]
        elif args.path:
            sys.argv += [args.path]
        else:
            parser.error("validate-conformance requires path or --all")
        if args.output:
            sys.argv += ["--output", args.output]
        vc.main()

    elif args.command == "conformance-impact":
        from dpm.validators import conformance_impact as ci

        sys.argv = [
            "conformance_impact",
            "--entity", args.entity,
            "--version", args.version,
            "--base-path", args.base_path,
        ]
        if args.output:
            sys.argv += ["--output", args.output]
        ci.main()


if __name__ == "__main__":
    main()
