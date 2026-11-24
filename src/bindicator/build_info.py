"""Expose the exact revision copied into the installed service.

Build metadata is produced once by deploy/install.sh. Runtime never invokes git
or reads the source checkout. Source/editable installations can lack metadata.
"""
from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re

_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def installed_commit(info_file: Path | None = None) -> str | None:
    """Return a validated seven-character commit prefix, or None."""
    path = info_file if info_file is not None else Path(__file__).with_name("_build_info.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    commit = data.get("commit")
    if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit):
        return None
    return commit[:7]


def display_version(info_file: Path | None = None) -> str:
    """Display installed Python version and, when available, the source SHA."""
    try:
        package_version = version("bindicator")
    except PackageNotFoundError:
        package_version = "development"
    commit = installed_commit(info_file)
    return f"{package_version} ({commit})" if commit else package_version
