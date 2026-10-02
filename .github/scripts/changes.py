# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The checks a pull request's changed files need: everything runs unless a rule skips it.

Usage:
    git diff --name-only --no-renames HEAD^1 HEAD | python3 .github/scripts/changes.py pull_request
    python3 .github/scripts/changes.py <any other event>   # every check, nothing read

Prints one `<check>=true|false` line per check, for $GITHUB_OUTPUT. A check is
skipped only when every changed file is in groups it doesn't need; a file in no
group (this script included) and an empty diff run every check.
"""

import sys

# A group's entries: a folder ends with "/", anything else is one file.
AGENT = (
    ".claude/",
    ".compound-engineering/",
    "CLAUDE.md",
    "CONCEPTS.md",
    "STRATEGY.md",
    "docs/plans/",
    "docs/solutions/",
    "docs/superpowers/",
    "docs/ideation/",
)
GROUPS: dict[str, tuple[str, ...]] = {
    "code": (
        "custom_components/",
        "tests/",
        "pyproject.toml",
        "uv.lock",
        "ruff.toml",
        "mypy.ini",
        "fetch_hassfest.py",
        "release.py",
        "sonar-project.properties",
    ),
    "workflows": (".github/workflows/",),
    # Plus every docs/**/*.mdx outside AGENT's folders (groups()).
    "docs": ("docs.json", "package.json", "pnpm-lock.yaml"),
    "hacs": ("hacs.json", "custom_components/pururu/manifest.json", "README.md"),
    # The repo's own tools, apart from the integration; the Python environment their tests run in
    "tools": ("tools/",),
    "env": ("pyproject.toml", "uv.lock"),
    # The acceptance suite, its own uv project; it also reads docs/, the translations and the root pins
    "acceptance": ("acceptance/",),
    "agent": AGENT,
}
NEEDS: dict[str, frozenset[str]] = {
    "build": frozenset({"code", "workflows"}),
    "docs": frozenset({"code", "docs", "workflows"}),
    "hacs": frozenset({"hacs", "workflows"}),
    "tools": frozenset({"tools", "env", "workflows"}),
    "acceptance": frozenset({"code", "docs", "env", "workflows", "acceptance"}),
}


def matches(path: str, entry: str) -> bool:
    """The path is the file `entry`, or under the folder `entry`."""
    return path.startswith(entry) if entry.endswith("/") else path == entry


def groups(path: str) -> set[str]:
    """Every group the path is in; the manifest is code and HACS, pyproject.toml and uv.lock code and env."""
    found = {
        name
        for name, entries in GROUPS.items()
        if any(matches(path, e) for e in entries)
    }
    if "agent" not in found and path.startswith("docs/") and path.endswith(".mdx"):
        found.add("docs")
    return found


def needed(paths: list[str]) -> dict[str, bool]:
    """Each check, run when any path needs it; a path in no group needs them all."""
    if not paths:
        return dict.fromkeys(NEEDS, True)
    run: set[str] = set()
    for path in paths:
        found = groups(path)
        run |= {check for check, wants in NEEDS.items() if not found or found & wants}
    return {check: check in run for check in NEEDS}


def lines(checks: dict[str, bool]) -> str:
    """`<check>=true|false`, one line each."""
    return "".join(f"{check}={str(run).lower()}\n" for check, run in checks.items())


def main(argv: list[str]) -> int:
    """Print the checks the event's changes need."""
    if len(argv) != 2:
        sys.stdout.write(f"{__doc__}\n")
        return 2
    if argv[1] == "pull_request":
        checks = needed(
            [line for line in sys.stdin.read().splitlines() if line.strip()]
        )
    else:
        checks = dict.fromkeys(NEEDS, True)
    sys.stdout.write(lines(checks))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
