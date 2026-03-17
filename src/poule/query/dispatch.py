"""Command dispatcher: maps (command, argument) to Coq vernacular strings."""

from __future__ import annotations


def build_vernacular(command: str, argument: str) -> str:
    """Construct a Coq vernacular string from a command name and argument.

    Appends a terminating period if the argument does not already end with one.
    The argument text is passed verbatim -- no escaping, quoting, or rewriting.
    """
    arg = argument.rstrip()
    if arg.endswith("."):
        return f"{command} {arg}"
    return f"{command} {arg}."
