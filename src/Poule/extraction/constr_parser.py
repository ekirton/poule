"""Parser that converts coq-lsp JSON output into ConstrNode types.

The JSON format uses two-element arrays: ``["Tag", payload]``.
"""

from __future__ import annotations

from Poule.extraction.errors import ExtractionError
from Poule.normalization import constr_node as cn

_JSON_VARIANT_MAP = {
    "Rel", "Var", "Sort", "Cast", "Prod", "Lambda", "LetIn",
    "App", "Const", "Ind", "Construct", "Case", "Fix", "CoFix",
    "Proj", "Int", "Float",
}


def parse_constr_json(raw: dict | list) -> cn.Rel | cn.Var | cn.Sort | cn.Cast | cn.Prod | cn.Lambda | cn.LetIn | cn.App | cn.Const | cn.Ind | cn.Construct | cn.Case | cn.Fix | cn.CoFix | cn.Proj | cn.Int | cn.Float:
    """Parse a coq-lsp JSON term into a ConstrNode.

    The JSON format uses two-element arrays: ``["Tag", payload]``.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) < 1:
        raise ExtractionError(f"Expected JSON array for Constr term, got: {type(raw).__name__}")

    tag = raw[0]
    if tag not in _JSON_VARIANT_MAP:
        raise ExtractionError(f"Unrecognized Constr variant: {tag!r}")

    if tag == "Rel":
        return cn.Rel(n=_expect_int(raw[1], "Rel index"))

    if tag == "Var":
        return cn.Var(name=_expect_str(raw[1], "Var name"))

    if tag == "Sort":
        sort_val = raw[1]
        if isinstance(sort_val, str):
            return cn.Sort(sort=sort_val)
        if isinstance(sort_val, list) and len(sort_val) >= 1:
            return cn.Sort(sort=str(sort_val[0]))
        return cn.Sort(sort=str(sort_val))

    if tag == "Cast":
        if len(raw) < 4:
            raise ExtractionError("Cast requires term, kind, and type")
        term = parse_constr_json(raw[1])
        # raw[2] is the cast kind — discard
        typ = parse_constr_json(raw[3])
        return cn.Cast(term=term, type=typ)

    if tag == "Prod":
        if len(raw) < 4:
            raise ExtractionError("Prod requires binder, type, and body")
        binder = raw[1]
        name = _extract_binder_name(binder)
        typ = parse_constr_json(raw[2])
        body = parse_constr_json(raw[3])
        return cn.Prod(name=name, type=typ, body=body)

    if tag == "Lambda":
        if len(raw) < 4:
            raise ExtractionError("Lambda requires binder, type, and body")
        binder = raw[1]
        name = _extract_binder_name(binder)
        typ = parse_constr_json(raw[2])
        body = parse_constr_json(raw[3])
        return cn.Lambda(name=name, type=typ, body=body)

    if tag == "LetIn":
        if len(raw) < 5:
            raise ExtractionError("LetIn requires binder, def, type, and body")
        binder = raw[1]
        name = _extract_binder_name(binder)
        val = parse_constr_json(raw[2])
        typ = parse_constr_json(raw[3])
        body = parse_constr_json(raw[4])
        return cn.LetIn(name=name, value=val, type=typ, body=body)

    if tag == "App":
        if len(raw) < 3:
            raise ExtractionError("App requires function and arguments")
        func = parse_constr_json(raw[1])
        args_raw = raw[2]
        if not isinstance(args_raw, list):
            raise ExtractionError("App arguments must be a list")
        args = [parse_constr_json(a) for a in args_raw]
        return cn.App(func=func, args=args)

    if tag == "Const":
        payload = raw[1]
        fqn = _extract_const_fqn(payload)
        return cn.Const(fqn=fqn)

    if tag == "Ind":
        payload = raw[1]
        fqn = _extract_ind_fqn(payload)
        return cn.Ind(fqn=fqn)

    if tag == "Construct":
        payload = raw[1]
        fqn = _extract_ind_fqn(payload)
        index = payload.get("constructor", 1) if isinstance(payload, dict) else 1
        return cn.Construct(fqn=fqn, index=index)

    if tag == "Case":
        if len(raw) < 4:
            raise ExtractionError("Case requires case_info, scrutinee, and branches")
        case_info = raw[1]
        ind_name = ""
        if isinstance(case_info, dict):
            ind_name = case_info.get("inductive", case_info.get("ind_name", ""))
        elif isinstance(case_info, list) and len(case_info) >= 1:
            ind_name = str(case_info[0]) if not isinstance(case_info[0], list) else ""
        scrutinee = parse_constr_json(raw[2])
        branches_raw = raw[3]
        if not isinstance(branches_raw, list):
            branches_raw = []
        branches = [parse_constr_json(b) for b in branches_raw]
        return cn.Case(ind_name=ind_name, scrutinee=scrutinee, branches=branches)

    if tag == "Fix":
        if len(raw) < 4:
            raise ExtractionError("Fix requires fix_info, types, and bodies")
        fix_info = raw[1]
        index = 0
        if isinstance(fix_info, int):
            index = fix_info
        elif isinstance(fix_info, dict):
            index = fix_info.get("index", 0)
        # raw[2] = types (discard), raw[3] = bodies
        bodies_raw = raw[3] if len(raw) > 3 else raw[2]
        if not isinstance(bodies_raw, list):
            bodies_raw = [bodies_raw]
        bodies = [parse_constr_json(b) for b in bodies_raw]
        return cn.Fix(index=index, bodies=bodies)

    if tag == "CoFix":
        if len(raw) < 3:
            raise ExtractionError("CoFix requires index and bodies")
        fix_info = raw[1]
        index = 0
        if isinstance(fix_info, int):
            index = fix_info
        elif isinstance(fix_info, dict):
            index = fix_info.get("index", 0)
        bodies_raw = raw[-1]
        if not isinstance(bodies_raw, list):
            bodies_raw = [bodies_raw]
        bodies = [parse_constr_json(b) for b in bodies_raw]
        return cn.CoFix(index=index, bodies=bodies)

    if tag == "Proj":
        if len(raw) < 3:
            raise ExtractionError("Proj requires projection info and term")
        proj_info = raw[1]
        name = ""
        if isinstance(proj_info, dict):
            name = proj_info.get("projection", "")
        elif isinstance(proj_info, str):
            name = proj_info
        term = parse_constr_json(raw[2])
        return cn.Proj(name=name, term=term)

    if tag == "Int":
        return cn.Int(value=_expect_int(raw[1], "Int value"))

    if tag == "Float":
        val = raw[1]
        if isinstance(val, (int, float)):
            return cn.Float(value=float(val))
        raise ExtractionError(f"Float value must be numeric, got: {type(val).__name__}")

    raise ExtractionError(f"Unrecognized Constr variant: {tag!r}")  # pragma: no cover


def _extract_binder_name(binder: dict | str) -> str:
    if isinstance(binder, str):
        return binder
    if isinstance(binder, dict):
        return binder.get("binder_name", binder.get("name", "_"))
    return "_"


def _extract_const_fqn(payload: dict | str) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return payload.get("constant", payload.get("fqn", ""))
    raise ExtractionError(f"Cannot extract FQN from Const payload: {payload!r}")


def _extract_ind_fqn(payload: dict | str) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return payload.get("inductive", payload.get("fqn", ""))
    raise ExtractionError(f"Cannot extract FQN from Ind/Construct payload: {payload!r}")


def _expect_int(val: object, context: str) -> int:
    if isinstance(val, int):
        return val
    raise ExtractionError(f"{context} must be an integer, got: {type(val).__name__}")


def _expect_str(val: object, context: str) -> str:
    if isinstance(val, str):
        return val
    raise ExtractionError(f"{context} must be a string, got: {type(val).__name__}")
