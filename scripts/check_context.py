"""Context hygiene gate for Project GRID.

Runs in pre-commit, CI, pytest (tests/test_context_hygiene.py) and Claude Code
session hooks. Exits non-zero when any FAIL-severity finding exists.

Checks (see docs/context/conventions.md#context-maintenance):
 1  CLAUDE.md within budget (<=150 lines, <=1200 words)             FAIL
 2  every docs/context/*.md has valid, complete front matter        FAIL
 3  every context file listed in CLAUDE.md pointer table + INDEX    FAIL
 4  every docs/-path referenced in CLAUDE.md exists                 FAIL
 5  verify_by not in the past                                       FAIL
 6  verify_by within 14 days                                        WARN
 7  drift: commits under covers_paths newer than last_verified      FAIL
 8  context file over 300 lines (split it)                          WARN
 9  every src/grid/sources adapter documented in data-sources       FAIL
10  every adapter declares SourceMeta with non-empty legal_basis    FAIL
11  ADR numbering contiguous, no duplicates                         WARN
12  .env.example covers every variable read by config.py            FAIL
13  no forbidden strings in tracked files (NRIC-like patterns,
    +60 mobile numbers outside tests/, *.xlsx/*.csv at repo root)   FAIL

Usage:
    python scripts/check_context.py [--fix] [--report]
      --fix     regenerate docs/context/INDEX.md from front matter
      --report  markdown-formatted output (for session hooks)

Only non-stdlib dependency: PyYAML.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    print("check_context: PyYAML missing — run `uv sync --all-groups`.", file=sys.stderr)
    sys.exit(2)

REPO = Path(__file__).resolve().parents[1]
CONTEXT_DIR = REPO / "docs" / "context"
INDEX_MD = CONTEXT_DIR / "INDEX.md"
CLAUDE_MD = REPO / "CLAUDE.md"
SOURCES_DIR = REPO / "src" / "grid" / "sources"
DECISIONS_DIR = REPO / "docs" / "decisions"
ENV_EXAMPLE = REPO / ".env.example"
CONFIG_PY = REPO / "src" / "grid" / "config.py"

MAX_CLAUDE_LINES = 150
MAX_CLAUDE_WORDS = 1200
MAX_CONTEXT_LINES = 300
VERIFY_HORIZON_DAYS = 90
WARN_WINDOW_DAYS = 14
VALID_STATUS = {"current", "needs-review", "stale"}
REQUIRED_KEYS = ("title", "owner", "last_verified", "verify_by", "status")

NRIC_RE = re.compile(r"\b\d{6}-\d{2}-\d{4}\b")
MOBILE_RE = re.compile(r"\+60\s?1\d[\s\-]?\d{3,4}[\s\-]?\d{3,4}")
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".xlsx",
    ".parquet",
    ".db",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".pyc",
}
SCAN_EXCLUDE = {"uv.lock"}


@dataclass
class Finding:
    check: str
    severity: str  # "FAIL" | "WARN"
    message: str


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def context_files() -> list[Path]:
    """All context markdown files, tolerating scoped subdirectories
    (e.g. data-sources/ becoming a directory). INDEX.md is the generated
    manifest and is excluded."""
    if not CONTEXT_DIR.is_dir():
        return []
    return sorted(p for p in CONTEXT_DIR.rglob("*.md") if p != INDEX_MD)


def front_matter(path: Path) -> dict[str, object] | None:
    text = read(path)
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def as_date(value: object) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def git(*args: str) -> str | None:
    """Run git in the repo; None if git/repo unavailable or the call fails."""
    try:
        proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def check_claude_budget(findings: list[Finding]) -> None:
    if not CLAUDE_MD.is_file():
        findings.append(Finding("1", "FAIL", "CLAUDE.md is missing."))
        return
    text = read(CLAUDE_MD)
    lines = len(text.splitlines())
    words = len(text.split())
    if lines > MAX_CLAUDE_LINES:
        findings.append(
            Finding("1", "FAIL", f"CLAUDE.md is {lines} lines (budget {MAX_CLAUDE_LINES}).")
        )
    if words > MAX_CLAUDE_WORDS:
        findings.append(
            Finding("1", "FAIL", f"CLAUDE.md is {words} words (budget {MAX_CLAUDE_WORDS}).")
        )


def check_front_matter(findings: list[Finding]) -> dict[Path, dict[str, object]]:
    metas: dict[Path, dict[str, object]] = {}
    today = dt.date.today()
    for path in context_files():
        meta = front_matter(path)
        name = rel(path)
        if meta is None:
            findings.append(Finding("2", "FAIL", f"{name}: missing or unparsable front matter."))
            continue
        missing = [k for k in REQUIRED_KEYS if k not in meta]
        if missing:
            findings.append(Finding("2", "FAIL", f"{name}: front matter missing {missing}."))
            continue
        last_verified = as_date(meta.get("last_verified"))
        verify_by = as_date(meta.get("verify_by"))
        if last_verified is None or verify_by is None:
            findings.append(
                Finding("2", "FAIL", f"{name}: last_verified/verify_by must be ISO dates.")
            )
            continue
        if (verify_by - last_verified).days > VERIFY_HORIZON_DAYS:
            findings.append(
                Finding(
                    "2",
                    "FAIL",
                    f"{name}: verify_by more than {VERIFY_HORIZON_DAYS} days after last_verified.",
                )
            )
        if meta.get("status") not in VALID_STATUS:
            findings.append(
                Finding("2", "FAIL", f"{name}: status must be one of {sorted(VALID_STATUS)}.")
            )
        covers = meta.get("covers_paths")
        if covers is not None and not isinstance(covers, list):
            findings.append(Finding("2", "FAIL", f"{name}: covers_paths must be a list."))
        metas[path] = meta
        if verify_by < today:
            findings.append(
                Finding("5", "FAIL", f"{name}: verify_by {verify_by} is in the past — re-verify.")
            )
        elif (verify_by - today).days <= WARN_WINDOW_DAYS:
            findings.append(
                Finding("6", "WARN", f"{name}: verify_by {verify_by} is within 14 days.")
            )
        line_count = len(read(path).splitlines())
        if line_count > MAX_CONTEXT_LINES:
            findings.append(
                Finding(
                    "8",
                    "WARN",
                    f"{name}: {line_count} lines (>{MAX_CONTEXT_LINES}) — apply the split "
                    "protocol (conventions.md#context-maintenance).",
                )
            )
    return metas


def check_pointers(findings: list[Finding]) -> None:
    claude = read(CLAUDE_MD) if CLAUDE_MD.is_file() else ""
    index = read(INDEX_MD) if INDEX_MD.is_file() else ""
    if not INDEX_MD.is_file():
        findings.append(
            Finding("3", "FAIL", "docs/context/INDEX.md missing — run with --fix to generate.")
        )
    for path in context_files():
        name = rel(path)
        parent = rel(path.parent) + "/"
        if name not in claude and parent not in claude:
            findings.append(
                Finding("3", "FAIL", f"{name}: not referenced in CLAUDE.md pointer table.")
            )
        if path.name not in index and name not in index:
            findings.append(Finding("3", "FAIL", f"{name}: not listed in INDEX.md."))
    # dead links: every docs/ or scripts/ path CLAUDE.md mentions must exist
    for match in re.findall(r"`((?:docs|scripts)/[^`\s]+)`", claude):
        target = REPO / match.rstrip("/")
        if not target.exists():
            findings.append(Finding("4", "FAIL", f"CLAUDE.md references missing path: {match}"))


def check_drift(findings: list[Finding], metas: dict[Path, dict[str, object]]) -> None:
    if git("rev-parse", "--verify", "HEAD") is None:
        return  # no commits yet — nothing to drift against
    for path, meta in metas.items():
        covers = meta.get("covers_paths") or []
        if not isinstance(covers, list) or not covers:
            continue
        last_verified = as_date(meta.get("last_verified"))
        if last_verified is None:
            continue
        since = last_verified + dt.timedelta(days=1)  # same-day commits count as verified
        pathspecs = [f":(glob){p}" for p in covers if isinstance(p, str)]
        out = git("log", "--oneline", f"--since={since.isoformat()} 00:00", "--", *pathspecs)
        if out and out.strip():
            commits = out.strip().splitlines()
            findings.append(
                Finding(
                    "7",
                    "FAIL",
                    f"{rel(path)}: code under covers_paths changed after last_verified "
                    f"({len(commits)} commit(s), e.g. '{commits[0]}') — re-verify the doc "
                    "and bump last_verified.",
                )
            )


def data_sources_text() -> str:
    """data-sources.md, tolerating the file becoming a directory of per-source files."""
    parts: list[str] = []
    single = CONTEXT_DIR / "data-sources.md"
    if single.is_file():
        parts.append(read(single))
    folder = CONTEXT_DIR / "data-sources"
    if folder.is_dir():
        parts.extend(read(p) for p in sorted(folder.glob("*.md")))
    return "\n".join(parts)


def check_adapters(findings: list[Finding]) -> None:
    if not SOURCES_DIR.is_dir():
        return
    docs = data_sources_text()
    for module in sorted(SOURCES_DIR.glob("*.py")):
        if module.stem in {"__init__", "base"}:
            continue
        name = rel(module)
        if f"`{module.stem}`" not in docs and module.stem not in docs:
            findings.append(Finding("9", "FAIL", f"{name}: adapter has no row in data-sources.md."))
        text = read(module)
        has_meta = "SourceMeta(" in text
        basis = re.search(r"legal_basis\s*=\s*(f?[\"'])(.*?)\1", text, re.DOTALL)
        if not has_meta or basis is None or not basis.group(2).strip():
            findings.append(
                Finding(
                    "10",
                    "FAIL",
                    f"{name}: adapter must declare SourceMeta with a non-empty legal_basis.",
                )
            )


def check_adrs(findings: list[Finding]) -> None:
    if not DECISIONS_DIR.is_dir():
        return
    numbers: list[int] = []
    for adr in sorted(DECISIONS_DIR.glob("*.md")):
        match = re.match(r"^(\d{4})-.+\.md$", adr.name)
        if match:
            numbers.append(int(match.group(1)))
    dupes = {n for n in numbers if numbers.count(n) > 1}
    if dupes:
        findings.append(Finding("11", "WARN", f"Duplicate ADR numbers: {sorted(dupes)}."))
    expected = list(range(1, len(set(numbers)) + 1))
    if sorted(set(numbers)) != expected:
        findings.append(
            Finding("11", "WARN", f"ADR numbering not contiguous: {sorted(set(numbers))}.")
        )


def settings_env_names() -> set[str]:
    """Env var names implied by the Settings class in config.py (prefix + field)."""
    if not CONFIG_PY.is_file():
        return set()
    source = read(CONFIG_PY)
    prefix_match = re.search(r"env_prefix\s*=\s*[\"']([^\"']*)[\"']", source)
    prefix = prefix_match.group(1) if prefix_match else ""
    names: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            base_names = {getattr(b, "id", getattr(b, "attr", "")) for b in node.bases}
            if not base_names & {"BaseSettings"}:
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    field = stmt.target.id
                    if not field.startswith("_") and field != "model_config":
                        names.add(f"{prefix}{field}".upper())
    return names


def check_env_example(findings: list[Finding]) -> None:
    expected = settings_env_names()
    if not expected:
        return
    if not ENV_EXAMPLE.is_file():
        findings.append(Finding("12", "FAIL", ".env.example is missing."))
        return
    documented = {
        m.group(1)
        for m in re.finditer(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", read(ENV_EXAMPLE), re.MULTILINE)
    }
    missing = sorted(expected - documented)
    if missing:
        findings.append(
            Finding("12", "FAIL", f".env.example missing variables read by config.py: {missing}.")
        )


def tracked_files() -> list[Path]:
    out = git("ls-files")
    if out is None:
        return [
            p
            for p in REPO.rglob("*")
            if p.is_file()
            and ".git" not in p.parts
            and ".venv" not in p.parts
            and "data" not in p.parts
        ]
    return [REPO / line for line in out.splitlines() if line.strip()]


def check_forbidden(findings: list[Finding]) -> None:
    for path in tracked_files():
        if not path.is_file() or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        relative = rel(path)
        if path.name in SCAN_EXCLUDE:
            continue
        try:
            text = read(path)
        except (UnicodeDecodeError, OSError):
            continue
        if NRIC_RE.search(text):
            findings.append(Finding("13", "FAIL", f"{relative}: candidate NRIC/IC pattern found."))
        if not relative.startswith("tests/") and MOBILE_RE.search(text):
            findings.append(
                Finding(
                    "13",
                    "FAIL",
                    f"{relative}: Malaysian mobile number pattern found in a non-test file.",
                )
            )
    for pattern in ("*.xlsx", "*.csv"):
        for stray in REPO.glob(pattern):
            findings.append(
                Finding("13", "FAIL", f"{stray.name}: {pattern} at repo root — move or delete.")
            )


def regenerate_index() -> None:
    rows: list[str] = []
    for path in context_files():
        meta = front_matter(path) or {}
        rows.append(
            "| {file} | {title} | {status} | {lv} | {vb} |".format(
                file=path.relative_to(CONTEXT_DIR).as_posix(),
                title=meta.get("title", "?"),
                status=meta.get("status", "?"),
                lv=meta.get("last_verified", "?"),
                vb=meta.get("verify_by", "?"),
            )
        )
    INDEX_MD.write_text(
        "# Context manifest\n\n"
        "> Machine-generated by `scripts/check_context.py --fix`. Do not edit by hand.\n"
        "> One row per context file; CLAUDE.md holds the human-facing pointer table.\n\n"
        "| File | Title | Status | Last verified | Verify by |\n"
        "|---|---|---|---|---|\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run_checks() -> list[Finding]:
    findings: list[Finding] = []
    check_claude_budget(findings)
    metas = check_front_matter(findings)
    check_pointers(findings)
    check_drift(findings, metas)
    check_adapters(findings)
    check_adrs(findings)
    check_env_example(findings)
    check_forbidden(findings)
    return findings


def emit(findings: list[Finding], report: bool) -> int:
    fails = [f for f in findings if f.severity == "FAIL"]
    warns = [f for f in findings if f.severity == "WARN"]
    if report:
        print("## Context hygiene report\n")
        if not findings:
            print("All checks green.")
        for f in findings:
            icon = "❌" if f.severity == "FAIL" else "⚠️"
            print(f"- {icon} **check {f.check}** — {f.message}")
        print(f"\n**{len(fails)} fail / {len(warns)} warn**")
    else:
        for f in findings:
            print(f"[{f.severity}] check {f.check}: {f.message}")
        print(f"check_context: {len(fails)} fail / {len(warns)} warn")
    return 1 if fails else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Project GRID context hygiene gate")
    parser.add_argument("--fix", action="store_true", help="regenerate INDEX.md")
    parser.add_argument("--report", action="store_true", help="markdown output")
    args = parser.parse_args()
    if args.fix:
        regenerate_index()
        print(f"regenerated {rel(INDEX_MD)}")
    return emit(run_checks(), report=args.report)


if __name__ == "__main__":
    sys.exit(main())
