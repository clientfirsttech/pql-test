# SPDX-License-Identifier: AGPL-3.0-only
"""``type: custom``, ``engine: pql-test`` rules: DAX written in the contract, checked by PQL.Assert.

Two forms of ``implementation``:

- ``{expression: <scalar DAX>, <one ODCS comparator>}`` compares the expression's value with
  the comparator through a PQL.Assert scalar assertion (``mustBe`` -> ``ShouldEqual``, ...).
- ``{function: PQL.Assert.<name>, args: [...]}`` calls any PQL.Assert assertion; pql-test
  supplies ``testName`` as the first argument. String arguments are DAX source.

The DAX is embedded in a generated suite's ``UNION``, so it must be one expression: a stray
``EVALUATE``, an unbalanced bracket, or a top-level comma would break every rule in the suite.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from pql_test.odcs.catalog import load_signatures
from pql_test.odcs.emit.dax import dax_literal
from pql_test.odcs.ir import CONTRACT_DAX, CONTRACT_DAX_SUITE, DIRECT_CALL, Assertion, RuleOutcome, Status, Target
from pql_test.odcs.mapping.context import MapContext, skipped
from pql_test.odcs.mapping.library import OPERATORS, severity_of
from pql_test.odcs.mapping.validity import CASE_INSENSITIVE
from pql_test.odcs.udf import version_key

ENGINE = "pql-test"
_COMPARATOR_OPS = {
    "mustBe": "dax.equal",
    "mustNotBe": "dax.not_equal",
    "mustBeGreaterThan": "dax.gt",
    "mustBeGreaterOrEqualTo": "dax.ge",
    "mustBeLessThan": "dax.lt",
    "mustBeLessOrEqualTo": "dax.le",
    "mustBeBetween": "dax.between",
    "mustNotBeBetween": "dax.not_between",
}
_FORMS = "implementation: {expression, <one comparator>} or {function, args}"
_KEYWORD_RE = re.compile(r"\b(EVALUATE|DEFINE)\b", re.IGNORECASE)
# Control characters and Unicode line breaks, except line feed and tab. A lone carriage return
# would end a // comment for a reader that normalises line ends but not for this scanner.
_CONTROL_RE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029]")
_CLOSERS = {")": "(", "}": "{"}
_DESCRIPTION_LIMIT = 80
# PQL.Assert 0.7.x compared a BLANK actual as 0 (numbers) or "" (ShouldEqualExactly); 0.8.0 fails it.
_BLANK_LENIENT_0_7 = {"dax.equal_exactly", "dax.gt", "dax.ge", "dax.lt", "dax.le", "dax.between"}
BLANK_PASSES_ON_0_7 = (
    "PQL.Assert 0.7 compares a BLANK result as 0 (or as an empty string), so a BLANK can pass; "
    "--pql-assert 0.8 fails it"
)


def is_pql_test_rule(rule: Mapping) -> bool:
    return rule.get("type") == "custom" and str(rule.get("engine", "")).lower() == ENGINE


def dax_problem(text: str) -> str | None:
    """Why *text* cannot be embedded as one argument of a generated call, or None when it can.

    Scans DAX outside string literals ("..."), quoted names ('...'), column references ([...]),
    and comments, so their contents never count.
    """
    control = _CONTROL_RE.search(text)
    if control:
        return f"a control character (U+{ord(control.group()):04X}); use line feeds and tabs only"
    code, i, stack = [], 0, []
    while i < len(text):
        ch, pair = text[i], text[i : i + 2]
        if pair in ("//", "--"):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        if pair == "/*":
            end = text.find("*/", i + 2)
            if end < 0:
                return "an unterminated /* comment"
            i = end + 2
            continue
        if ch in "\"'[":
            close = {'"': '"', "'": "'", "[": "]"}[ch]
            j = i + 1
            while j < len(text):
                if text[j] == close and text[j + 1 : j + 2] == close:
                    j += 2  # an escaped quote or bracket ("" '' ]])
                elif text[j] == close:
                    break
                else:
                    j += 1
            if j >= len(text):
                return f"an unterminated {ch}"
            code.append(" ")
            i = j + 1
            continue
        if ch in "({":
            stack.append(ch)
        elif ch in ")}":
            if not stack or stack.pop() != _CLOSERS[ch]:
                return f"an unbalanced {ch}"
        elif ch == "]":
            return "an unbalanced ]"
        elif ch == "," and not stack:
            return "a top-level comma (the DAX must be one expression)"
        code.append(ch)
        i += 1
    if stack:
        return f"an unclosed {stack[-1]}"
    keyword = _KEYWORD_RE.search("".join(code))
    if keyword:
        return f"{keyword.group(1).upper()} (the DAX must be an expression, not a query)"
    return None


def _describe(rule: Mapping, scope: str, detail: str) -> str:
    text = rule.get("description") or rule.get("name") or f"{scope} {detail}"
    text = " ".join(str(text).split())
    return text if len(text) <= _DESCRIPTION_LIMIT else text[: _DESCRIPTION_LIMIT - 3] + "..."


def map_dax_rule(ctx: MapContext, rule: Mapping, rule_id: str, obj: Mapping, scope: str) -> RuleOutcome:
    """Map one ``engine: pql-test`` rule to a PQL.Assert call, or skip it with the reason."""
    impl = rule.get("implementation")
    if not isinstance(impl, Mapping) or ("expression" in impl) == ("function" in impl):
        return skipped(rule_id, f"engine: pql-test needs {_FORMS}", _describe(rule, scope, "pql-test rule"))
    target = Target(ctx.names.table(obj))
    if "function" in impl:
        return _function_rule(ctx, rule, rule_id, target, scope, impl)
    return _expression_rule(ctx, rule, rule_id, target, scope, impl)


def _outcome(rule_id: str, assertion: Assertion, reason: str | None = None) -> RuleOutcome:
    status = Status.APPROXIMATED if reason else Status.MAPPED
    return RuleOutcome(
        rule_id, status, (assertion,), reason=reason, description=assertion.description, source=CONTRACT_DAX
    )


def _expression_rule(ctx, rule, rule_id, target, scope, impl) -> RuleOutcome:
    expression = impl["expression"]
    present = [k for k in OPERATORS if k in impl]
    detail = " ".join(str(p) for p in (expression, *(present[:1]), *(impl[k] for k in present[:1])))
    description = _describe(rule, scope, detail)
    if not isinstance(expression, str) or not expression.strip():
        return skipped(rule_id, "implementation.expression needs DAX text", description)
    problem = dax_problem(expression)
    if problem:
        return skipped(rule_id, f"implementation.expression has {problem}", description)
    if len(present) != 1:
        return skipped(rule_id, f"implementation needs exactly one comparator ({', '.join(OPERATORS)})", description)
    key, value = present[0], impl[present[0]]
    op, args, reason = _comparison(key, value)
    if op is None:
        return skipped(rule_id, args, description)
    if not ctx.supports(op):
        return skipped(rule_id, f"{key} on a DAX expression needs --pql-assert 0.8 (ShouldNotBeBetween)", description)
    assertion = Assertion(
        rule_id, CONTRACT_DAX_SUITE, op, target, {**args, "expression": expression}, description, severity_of(rule)
    )
    if reason is None and op in _BLANK_LENIENT_0_7 and version_key(ctx.catalog.min_version) < (0, 8):
        reason = BLANK_PASSES_ON_0_7
    return _outcome(rule_id, assertion, reason)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _comparison(key: str, value: Any) -> tuple[str | None, Any, str | None]:
    """``(ir op, args, approximation reason)``, or ``(None, skip reason, None)``."""
    if key in ("mustBeBetween", "mustNotBeBetween"):
        if not (isinstance(value, list) and len(value) == 2 and all(_is_number(v) for v in value)):
            return None, f"{key} needs two numbers", None
        return _COMPARATOR_OPS[key], {"lower": min(value), "upper": max(value)}, None
    if key in ("mustBe", "mustNotBe"):
        if not (isinstance(value, (str, bool)) or _is_number(value)):
            return None, f"{key} needs a text, finite number, or true/false value", None
        if key == "mustBe" and isinstance(value, str):
            return "dax.equal_exactly", {"expected": value}, None  # DAX `=` ignores case
        cased = isinstance(value, str) and value.lower() != value.upper()
        return _COMPARATOR_OPS[key], {"expected": value}, CASE_INSENSITIVE if cased else None
    if not _is_number(value):
        return None, f"{key} needs a finite number", None
    return _COMPARATOR_OPS[key], {"threshold": value}, None


def _function_rule(ctx, rule, rule_id, target, scope, impl) -> RuleOutcome:
    name, raw_args = impl["function"], impl.get("args", [])
    description = _describe(rule, scope, str(name))
    signatures = load_signatures()
    if version_key(ctx.catalog.min_version) < version_key(signatures.version):
        return skipped(
            rule_id,
            f"direct PQL.Assert calls need --pql-assert 0.8 (signatures from {signatures.version})",
            description,
        )
    if not isinstance(name, str):
        return skipped(rule_id, "implementation.function needs a PQL.Assert function name", description)
    signature = signatures.functions.get(name)
    if signature is None or not signature.callable:
        why = "is not a PQL.Assert function" if signature is None else "is not an assertion a contract can call"
        return skipped(rule_id, f"{name!r} {why}", description)
    if not isinstance(raw_args, list):
        return skipped(rule_id, "implementation.args needs a list", description)
    count = len(raw_args) + 1  # pql-test supplies testName
    if not signature.params - signature.optional <= count <= signature.params:
        return skipped(
            rule_id,
            f"{name} takes {signature.params - signature.optional}-{signature.params} arguments including testName, "
            f"got {count}",
            description,
        )
    arguments = []
    for i, arg in enumerate(raw_args):
        if isinstance(arg, bool) or _is_number(arg):
            arguments.append(dax_literal(arg))
            continue
        if not isinstance(arg, str):
            reason = f"implementation.args[{i}] must be DAX text, a finite number, or true/false"
            return skipped(rule_id, reason, description)
        problem = dax_problem(arg)
        if problem:
            return skipped(rule_id, f"implementation.args[{i}] has {problem}", description)
        arguments.append(arg.strip())
    args = {"function": name, "arguments": arguments}
    assertion = Assertion(rule_id, CONTRACT_DAX_SUITE, DIRECT_CALL, target, args, description, severity_of(rule))
    return _outcome(rule_id, assertion)
