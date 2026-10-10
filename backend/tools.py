"""Deterministic, read-only diagnostics for common GitHub Actions failures."""
from __future__ import annotations

import re
from typing import Any


_SECRET_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    (re.compile(r"\bASIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(x-api-key\s*[:=]\s*)[^\s]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(password\s*[:=]\s*)[^\s]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(token\s*[:=]\s*)(?!\$\{\{|\[REDACTED)[^\s]+"), r"\1[REDACTED]"),
)


_PATTERN_DEFINITIONS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "missing_dependency",
        "MODULE_NOT_FOUND",
        re.compile(
            r"(?i)(cannot find module|module_not_found|modulenotfounderror|no module named|npm err!.*missing)"
        ),
    ),
    (
        "missing_file_or_checkout",
        "MISSING_PATH",
        re.compile(
            r"(?i)(enoent|no such file or directory|filenotfounderror|cannot open .*file|file not found)"
        ),
    ),
    (
        "yaml_error",
        "YAML_PARSE_ERROR",
        re.compile(
            r"(?i)(yamlexception|scannererror|yaml.*(parse|syntax|invalid)|mapping values are not allowed|"
            r"did not find expected|could not find expected|bad indentation|found character.*tab)"
        ),
    ),
    (
        "permissions",
        "PERMISSION_DENIED",
        re.compile(
            r"(?i)(eacces|permission denied|accessdenied|access denied|403 forbidden|"
            r"resource not accessible by integration|insufficient permission|unauthorized)"
        ),
    ),
    (
        "missing_secret",
        "MISSING_SECRET",
        re.compile(
            r"(?i)(secret.{0,40}(not set|not found|missing|empty|undefined)|"
            r"(context access might be invalid|secret was not provided))"
        ),
    ),
    (
        "failing_test",
        "TEST_FAILURE",
        re.compile(
            r"(?i)(assertionerror|tests? failed|test suite failed|npm err!.*test|pytest.*failed|"
            r"^\s*fail(?:ed|ure)?\b|expect\(.*\).*to)"
        ),
    ),
    (
        "generic_failure",
        "NONZERO_EXIT",
        re.compile(r"(?i)(process completed with exit code\s+[1-9]\d*|exit status\s+[1-9]\d*)"),
    ),
)


_CATEGORY_PRIORITY = {
    "missing_dependency": 1,
    "missing_file_or_checkout": 2,
    "yaml_error": 3,
    "permissions": 4,
    "missing_secret": 5,
    "failing_test": 6,
    "generic_failure": 7,
}


def redact_secrets(text: str) -> str:
    """Remove common credential-shaped values without changing normal diagnostics."""
    if not isinstance(text, str):
        return ""
    redacted = text
    for pattern, replacement in _SECRET_REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _short_line(line: str, limit: int = 280) -> str:
    value = redact_secrets(line.strip())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _evidence_for_matches(lines: list[str], patterns: list[re.Pattern[str]]) -> list[str]:
    evidence: list[str] = []
    for line in lines:
        if any(pattern.search(line) for pattern in patterns):
            shortened = _short_line(line)
            if shortened and shortened not in evidence:
                evidence.append(shortened)
        if len(evidence) == 3:
            break
    return evidence


def classify_error(log_text: str) -> dict[str, Any]:
    """Classify a log using bounded patterns; never infer from repository access."""
    safe_log = redact_secrets(log_text or "")
    lines = safe_log.splitlines()
    matched: list[tuple[str, str, re.Pattern[str]]] = []

    for category, pattern_name, pattern in _PATTERN_DEFINITIONS:
        if pattern.search(safe_log):
            matched.append((category, pattern_name, pattern))

    if not matched:
        return {
            "category": "unknown",
            "matched_patterns": [],
            "evidence_lines": [],
            "confidence_hint": "low",
            "unknowns": ["The supplied text did not match a known failure signature."],
        }

    # A lone exit-code line is deliberately treated as insufficient context.
    if all(category == "generic_failure" for category, _, _ in matched):
        evidence = _evidence_for_matches(lines, [matched[0][2]])
        return {
            "category": "insufficient_context",
            "matched_patterns": [name for _, name, _ in matched],
            "evidence_lines": evidence,
            "confidence_hint": "low",
            "unknowns": [
                "The preceding error lines and the failing workflow step are not present.",
                "The exit code alone does not identify the root cause.",
            ],
        }

    category, _, _ = sorted(matched, key=lambda item: _CATEGORY_PRIORITY[item[0]])[0]
    category_patterns = [pattern for item_category, _, pattern in matched if item_category == category]
    evidence = _evidence_for_matches(lines, category_patterns)
    unknowns_by_category = {
        "missing_dependency": [
            "Whether the package is declared in the project manifest.",
            "Whether the workflow installs dependencies before the failing step.",
        ],
        "missing_file_or_checkout": [
            "Whether the path is correct relative to the runner working directory.",
            "Whether the repository was checked out before the file was read.",
        ],
        "yaml_error": ["The exact workflow file and line number containing the syntax error."],
        "permissions": ["Which GitHub token or action permission the failing step requires."],
        "missing_secret": ["Whether the expected secret exists in the repository or environment settings."],
        "failing_test": ["Which assertion or test fixture caused the failure."],
        "generic_failure": ["The preceding error output and the failing command."],
    }
    return {
        "category": category,
        "matched_patterns": [name for _, name, _ in matched],
        "evidence_lines": evidence,
        "confidence_hint": "high" if evidence else "medium",
        "unknowns": unknowns_by_category.get(category, []),
    }


def inspect_workflow(workflow_text: str) -> dict[str, Any]:
    """Inspect workflow text as data. No YAML or shell content is executed."""
    safe_workflow = redact_secrets(workflow_text or "")
    if not safe_workflow.strip():
        return {
            "provided": False,
            "has_checkout": None,
            "has_dependency_install": None,
            "permissions": None,
            "uses_references": [],
            "warnings": [],
            "parse_warning": None,
        }

    lines = safe_workflow.splitlines()
    uses_references: list[str] = []
    for match in re.finditer(r"(?im)^\s*(?:-\s*)?uses:\s*([^\s#]+)", safe_workflow):
        reference = match.group(1).strip()
        if reference not in uses_references:
            uses_references.append(reference)

    has_checkout = any(reference.lower().startswith("actions/checkout@") for reference in uses_references)
    has_dependency_install = bool(
        re.search(
            r"(?im)^\s*(?:-|\s)*(?:run:\s*)?(?:npm\s+(?:ci|install)|pnpm\s+install|yarn\s+install|"
            r"pip\s+install|poetry\s+install|bundle\s+install|go\s+mod\s+download)\b",
            safe_workflow,
        )
    )

    permissions_match = re.search(r"(?im)^\s*permissions\s*:\s*(.*)$", safe_workflow)
    permissions = permissions_match.group(1).strip() if permissions_match else None
    warnings: list[str] = []
    parse_warning: str | None = None

    if any(re.match(r"^\s*\t", line) for line in lines):
        parse_warning = "The workflow contains tab indentation; YAML should use spaces."
    elif safe_workflow.count("\"") % 2 or safe_workflow.count("'") % 2:
        parse_warning = "The workflow may contain an unmatched quote; verify YAML syntax before running it."

    if not has_checkout:
        warnings.append("No actions/checkout step was detected; repository files may be unavailable to later steps.")
    if not has_dependency_install:
        warnings.append("No dependency-install step was detected; confirm the failing job installs its packages.")
    if permissions is None:
        warnings.append("No permissions block was detected; review token permissions with least privilege in mind.")

    unsafe_env = bool(
        re.search(
            r"(?i)(?:run:\s*.*(?:printenv|\benv\b)|echo\s+.*\$\{\{\s*secrets\.|"
            r"env:\s*\n(?:.|\n){0,200}\$\{\{\s*secrets\.)",
            safe_workflow,
        )
    )
    if unsafe_env:
        warnings.append("A step may print a secret-derived value; avoid echoing credentials into logs.")

    return {
        "provided": True,
        "has_checkout": has_checkout,
        "has_dependency_install": has_dependency_install,
        "permissions": permissions,
        "uses_references": uses_references[:20],
        "warnings": warnings,
        "parse_warning": parse_warning,
    }


def suggest_checklist(category: str) -> list[dict[str, str]]:
    """Return safe, curated checks for a classified category."""
    checklists: dict[str, list[dict[str, str]]] = {
        "missing_dependency": [
            {"label": "Declare the package", "detail": "Confirm the dependency is in package.json and the lockfile is committed."},
            {"label": "Install before the failing step", "detail": "Use npm ci (or the package manager's lockfile-aware equivalent) in the workflow."},
        ],
        "missing_file_or_checkout": [
            {"label": "Check repository checkout", "detail": "Place actions/checkout before any step that reads repository files."},
            {"label": "Check the path", "detail": "Verify the path and working-directory are correct for the runner."},
        ],
        "yaml_error": [
            {"label": "Validate indentation", "detail": "Use spaces consistently and check the reported line and its parent block."},
            {"label": "Validate locally", "detail": "Run a YAML linter without executing the workflow contents."},
        ],
        "permissions": [
            {"label": "Identify the blocked operation", "detail": "Read the action or API named in the error before changing permissions."},
            {"label": "Use least privilege", "detail": "Add only the specific job permission required, and never paste a token into the log."},
        ],
        "missing_secret": [
            {"label": "Check configuration", "detail": "Confirm the expected secret exists in the correct repository or environment scope."},
            {"label": "Keep values private", "detail": "Do not print, paste, or request the secret value itself."},
        ],
        "failing_test": [
            {"label": "Read the first assertion", "detail": "Start at the first failed assertion and compare the expected and actual values."},
            {"label": "Reproduce narrowly", "detail": "Run only the failing test locally with the same runtime version when possible."},
        ],
        "generic_failure": [
            {"label": "Collect the preceding lines", "detail": "The exit code is a symptom; capture the failing command and 20–40 lines before it."},
        ],
        "unknown": [
            {"label": "Add context", "detail": "Capture the failing step, command, and the first meaningful error line."},
        ],
        "insufficient_context": [
            {"label": "Add context", "detail": "Paste the preceding 20–40 log lines and the relevant workflow step."},
        ],
    }
    return checklists.get(category, checklists["unknown"])
