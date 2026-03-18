"""Version detection utilities for Coq and installed libraries."""

from __future__ import annotations

import re
import subprocess

from .errors import CoqNotInstalledError


def detect_coq_version() -> str:
    """Detect the installed Coq/Rocq version by running ``coqc --version``.

    Returns
    -------
    str
        The version string, e.g. ``"8.19.0"`` or ``"9.0.0"``.

    Raises
    ------
    CoqNotInstalledError
        If ``coqc`` is not found on the system.
    """
    try:
        result = subprocess.run(
            ["coqc", "--version"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise CoqNotInstalledError(
            f"coqc not found: {exc}. Install Coq via opam: opam install coq"
        ) from exc

    output = result.stdout.strip()
    # Match patterns like "The Coq Proof Assistant, version 8.19.0"
    # or "The Rocq Prover, version 9.0.0"
    match = re.search(r"version\s+(\d+\.\d+(?:\.\d+)?)", output)
    if match:
        return match.group(1)

    # Fallback: return the first version-like string
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", output)
    if match:
        return match.group(1)

    return output


def detect_mathcomp_version() -> str:
    """Detect the installed MathComp version.

    Returns
    -------
    str
        The version string, or ``"none"`` if MathComp is not installed.
    """
    try:
        result = subprocess.run(
            ["opam", "show", "coq-mathcomp-ssreflect", "--field=version"],
            capture_output=True,
            text=True,
        )
        version = result.stdout.strip().strip('"')
        if result.returncode == 0 and version:
            return version
    except FileNotFoundError:
        pass

    return "none"


_OPAM_PACKAGES = {
    "mathcomp": "coq-mathcomp-ssreflect",
    "stdpp": "coq-stdpp",
    "flocq": "coq-flocq",
    "coquelicot": "coq-coquelicot",
    "coqinterval": "coq-interval",
}


def detect_library_version(library: str) -> str:
    """Detect the installed version of a Coq library.

    Parameters
    ----------
    library
        Library identifier: ``"stdlib"``, ``"mathcomp"``, ``"stdpp"``,
        ``"flocq"``, ``"coquelicot"``, or ``"coqinterval"``.

    Returns
    -------
    str
        The version string, or ``"none"`` if the library is not installed.
    """
    if library == "stdlib":
        try:
            return detect_coq_version()
        except CoqNotInstalledError:
            return "none"

    package = _OPAM_PACKAGES.get(library)
    if package is None:
        return "none"

    try:
        result = subprocess.run(
            ["opam", "show", package, "--field=version"],
            capture_output=True,
            text=True,
        )
        version = result.stdout.strip().strip('"')
        if result.returncode == 0 and version:
            return version
    except FileNotFoundError:
        pass

    return "none"
