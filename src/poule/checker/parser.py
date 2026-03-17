"""Output parsing for coqchk subprocess results.

Spec: specification/independent-proof-checking.md, Section 4.7.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from poule.checker.types import CheckFailure

# Compiled patterns in priority order
_CHECKED_RE = re.compile(r"^(\S+) has been checked$", re.MULTILINE)

# Priority 1: inconsistency
_INCONSISTENCY_RE = re.compile(
    r"Error:\s+(\S+)\s+is not consistent with\s+(\S+)"
)

# Priority 2: missing dependency
_MISSING_LIB_RE = re.compile(
    r"(?:Error:\s+Missing library|Cannot find library)\s+(\S+)"
)

# Priority 3: type error / anomaly
_TYPE_ERROR_RE = re.compile(
    r"(?:Error:\s+Anomaly|Type error)"
)
_TYPE_ERROR_DEF_RE = re.compile(
    r"(?:Type error in definition|Error: Anomaly in)\s+(\S+)"
)

# Priority 4: axiom mismatch
_AXIOM_MISMATCH_RE = re.compile(
    r"Error:.*\(axiom\).*mismatch|Error:\s+(\S+)\s+\(axiom\)"
)


def parse_output(
    stdout: str,
    stderr: str,
    exit_code: Optional[int],
    library_names: List[str],
) -> Tuple[int, int, int, List[CheckFailure]]:
    """Parse coqchk output into structured results.

    Returns (files_checked, files_passed, files_failed, failures).
    """
    failures: List[CheckFailure] = []

    # Count success lines from stdout
    checked_modules = _CHECKED_RE.findall(stdout)
    files_passed = len(checked_modules)

    # On exit code 0, all submitted libraries are checked
    if exit_code == 0:
        files_checked = max(len(library_names), files_passed)
        return files_checked, files_passed, 0, []

    # On exit code None (timeout/kill), return what we can parse
    # The caller (check_single) handles the synthetic timeout failure
    if exit_code is None:
        files_checked = len(library_names)
        return files_checked, files_passed, 0, []

    # Non-zero exit code: parse stderr for failures
    files_failed = 0
    failed_modules = set()

    for line in stderr.splitlines():
        line = line.strip()
        if not line:
            continue

        failure = _classify_line(line)
        if failure is not None:
            failures.append(failure)
            if failure.module_name:
                failed_modules.add(failure.module_name)
            files_failed += 1

    # If non-zero exit but no parseable errors, create an unknown failure
    if not failures:
        failures.append(
            CheckFailure(
                file_path="",
                module_name=None,
                definition=None,
                failure_kind="unknown",
                raw_message=stderr or stdout or "coqchk exited with non-zero status",
            )
        )
        files_failed = 1

    files_checked = len(library_names)

    return files_checked, files_passed, files_failed, failures


def _classify_line(line: str) -> Optional[CheckFailure]:
    """Classify a single stderr line into a CheckFailure, or None if not an error."""

    # Priority 1: inconsistency
    m = _INCONSISTENCY_RE.search(line)
    if m:
        return CheckFailure(
            file_path="",
            module_name=m.group(1),
            definition=None,
            failure_kind="inconsistency",
            raw_message=line,
        )

    # Priority 2: missing dependency
    m = _MISSING_LIB_RE.search(line)
    if m:
        return CheckFailure(
            file_path="",
            module_name=m.group(1),
            definition=None,
            failure_kind="missing_dependency",
            raw_message=line,
        )

    # Priority 3: type error / anomaly
    m = _TYPE_ERROR_RE.search(line)
    if m:
        # Try to extract definition name
        dm = _TYPE_ERROR_DEF_RE.search(line)
        definition = dm.group(1) if dm else None
        return CheckFailure(
            file_path="",
            module_name=None,
            definition=definition,
            failure_kind="type_error",
            raw_message=line,
        )

    # Priority 4: axiom mismatch
    m = _AXIOM_MISMATCH_RE.search(line)
    if m:
        return CheckFailure(
            file_path="",
            module_name=None,
            definition=None,
            failure_kind="axiom_mismatch",
            raw_message=line,
        )

    # Priority 5: any other Error: line
    if line.startswith("Error:"):
        return CheckFailure(
            file_path="",
            module_name=None,
            definition=None,
            failure_kind="unknown",
            raw_message=line,
        )

    return None
