#!/usr/bin/env python3
"""Shared validation report primitives.

These types are reused by the governance validator and the conformance
validator so that both speak the same finding vocabulary (rule code,
severity, message, path, suggestion).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """Severity levels for findings."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Finding:
    """A single validation finding."""

    rule: str
    severity: Severity
    message: str
    path: str = ""
    suggestion: str = ""


@dataclass
class ValidationReport:
    """Validation report for a single manifest."""

    manifest_path: str
    findings: list[Finding] = field(default_factory=list)
    passed: bool = True

    def add_finding(self, finding: Finding) -> None:
        """Add a finding to the report and flip ``passed`` on errors."""
        self.findings.append(finding)
        if finding.severity == Severity.ERROR:
            self.passed = False

    @property
    def error_count(self) -> int:
        """Count of error findings."""
        return sum(1 for f in self.findings if f.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count of warning findings."""
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)

    @property
    def info_count(self) -> int:
        """Count of info findings."""
        return sum(1 for f in self.findings if f.severity == Severity.INFO)


def print_report(report: ValidationReport) -> None:
    """Print a validation report to stdout."""
    status = "OK" if report.passed else "FAILED"
    print(f"\n{'=' * 60}")
    print(f"Manifest: {report.manifest_path}")
    print(f"Status: {status}")
    print(
        f"Errors: {report.error_count} | "
        f"Warnings: {report.warning_count} | Info: {report.info_count}"
    )
    print(f"{'=' * 60}")

    if report.findings:
        for finding in report.findings:
            icon = {"error": "[X]", "warning": "[!]", "info": "[i]"}[finding.severity.value]
            print(f"  {icon} [{finding.rule}] {finding.message}")
            if finding.path:
                print(f"      Path: {finding.path}")
            if finding.suggestion:
                print(f"      Suggestion: {finding.suggestion}")
    else:
        print("  No issues found")
