# Refactor A2-layout: one folder per layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the integration's modules into one folder per layer (D21), changing nothing else.

**Architecture:** A pure move, done by a script so no body is touched by hand: `git mv` each module, then rewrite every relative import from its resolved absolute target, and the test's module paths. The unchanged tests (only module paths edited), `tests/test_ids.py`, the per-function coverage comparison and an AST comparison of every moved module prove it. The import test's rules become rules per folder.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, pytest, ruff, mypy strict, uv.

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md` — D21, PR A2-layout.

**Base:** stacked on `refactor/a2a-lifecycle` (PR #44); retargeted to `main` once #44 merges.

## Global Constraints

- Behaviour identical. Tests change only where they name a module path (`helpers.module("…")`, `tests/test_generated.py`'s case module); no assertion changes.
- Every moved module's AST identical apart from its `from … import` lines.
- `tests/test_ids.py` unchanged and passing; per-function coverage not lower.
- At the root, only what HA requires there: `__init__.py`, `config_flow.py`, `const.py`, `sensor.py`, `binary_sensor.py`, `switch.py`, `light.py`, and the non-Python files.
- `uv run pytest` green at every commit. Version stays `0.2.0`.
- Commits end with the two attribution lines.
- The PR opens only after the local final review is done and its findings are fixed.

## Review Focus

1. **An import rewritten to the wrong module.** A relative import resolved against the old path and re-emitted against the new one; a mistake shows as an ImportError at collection, or worse, an import of a same-named module in another folder (`devices` vs `device_keys`).
2. **Comments or `# noqa` inside an import statement** lost when the statement is regenerated.
3. **`TYPE_CHECKING` imports** rewritten too (they're `ImportFrom` nodes like any other).
4. **Sonar suppressions and docs** naming a moved file.
5. **HA looking up a moved name.** HA imports only the root modules (entry points, `config_flow`, platforms); nothing it looks up moves.

---

## The layout

| Folder | Modules |
|---|---|
| root | `__init__`, `config_flow`, `const`, `sensor`, `binary_sensor`, `switch`, `light` |
| `core/` | `runtime`, `feature`, `vocabulary`, `entity`, `texts`, `messages`, `files`, `generated` |
| `features/` | unchanged |
| `device_keys/` | `device_keys.py` becomes `device_keys/__init__.py` (it holds `DEVICE_KEYS`); `programs`, `reactions`, `notifications` (until B moves it to `aspects/`) |
| `outputs/` | `events`, `dashboard`, `places`, `devices`, `alert2_alerts`, `alert_lights` |
| `setup/` | `schema`, `catalogue`, `checks`, `build`, `generate`, `lifecycle`, `listener` |

---

### Task 1: The move, by script

**Files:** every module above; `tests/*.py` where a module path is named; `sonar-project.properties`.

- [ ] **Step 1: Coverage baseline** — `uv run pytest --cov --cov-branch --cov-report=json:<workspace>/coverage-before.json -q`.

- [ ] **Step 2: Write the script** `<workspace>/relayout.py`:

```python
"""Move modules into their folders and rewrite every relative import from its resolved target."""

import ast
import subprocess
from pathlib import Path

ROOT = Path("custom_components/pururu")
MOVES = {  # old dotted module (relative to the package) -> new
    **{m: f"core.{m}" for m in ("runtime", "feature", "vocabulary", "entity", "texts", "messages", "files", "generated")},
    "device_keys": "device_keys",  # device_keys.py -> device_keys/__init__.py
    **{m: f"device_keys.{m}" for m in ("programs", "reactions", "notifications")},
    **{m: f"outputs.{m}" for m in ("events", "dashboard", "places", "devices", "alert2_alerts", "alert_lights")},
    **{m: f"setup.{m}" for m in ("schema", "catalogue", "checks", "build", "generate", "lifecycle", "listener")},
}
PACKAGES = {"core", "device_keys", "outputs", "setup"}


def dotted(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def is_package(path: Path) -> bool:
    return path.name == "__init__.py"


def resolve(module: str, pkg_of: str, node: ast.ImportFrom) -> list[tuple[str, str | None]]:
    """(absolute dotted target, imported name or None) for each alias; target is a module when name is None."""
    base = pkg_of.split(".") if pkg_of else []
    base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
    if node.module:
        return [(".".join([*base, *node.module.split(".")]), alias.name) for alias in node.names]
    return [(".".join([*base, alias.name]), None) for alias in node.names]


# 1. The old dotted name of every file, before moving
files = {path: dotted(path) for path in ROOT.rglob("*.py")}
# 2. Move
for package in PACKAGES:
    (ROOT / package).mkdir(exist_ok=True)
for old, new in MOVES.items():
    src = ROOT / f"{old}.py"
    dst = ROOT / (f"{new.replace('.', '/')}/__init__.py" if old == new else f"{new.replace('.', '/')}.py")
    subprocess.run(["git", "mv", str(src), str(dst)], check=True)
for package in PACKAGES - {"device_keys"}:
    init = ROOT / package / "__init__.py"
    if not init.exists():
        init.write_text(f'"""{package}: see docs/develop/architecture.mdx."""\n')
        subprocess.run(["git", "add", str(init)], check=True)


def new_name(old: str) -> str:
    head, _, rest = old.partition(".")
    for candidate in (old, head):
        if candidate in MOVES:
            return MOVES[candidate] + old[len(candidate):]
    return old


def relative(target: str, from_pkg: str) -> tuple[int, str]:
    """(level, module) of a relative import of `target` from package `from_pkg`."""
    here = from_pkg.split(".") if from_pkg else []
    there = target.split(".")
    common = 0
    while common < len(here) and common < len(there) - 1 and here[common] == there[common]:
        common += 1
    return len(here) - common + 1, ".".join(there[common:])


# 3. Rewrite every file's relative imports from its new location
for old_path, old_dotted in files.items():
    new_dotted = new_name(old_dotted)
    new_path = ROOT / (new_dotted.replace(".", "/") + ("/__init__.py" if old_path.name == "__init__.py" or old_dotted == "device_keys" else ".py"))
    if old_dotted == "":
        new_path = ROOT / "__init__.py"
    text = new_path.read_text()
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    old_pkg = old_dotted if is_package(old_path) else old_dotted.rpartition(".")[0]
    new_pkg = new_dotted if (is_package(old_path) or old_dotted == "device_keys") else new_dotted.rpartition(".")[0]
    for node in sorted((n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level), key=lambda n: -n.lineno):
        indent = lines[node.lineno - 1][: len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())]
        groups: dict[tuple[int, str], list[str]] = {}
        for target, name in resolve(old_dotted, old_pkg, node):
            alias = next(a for a in node.names if a.name == (name or target.rpartition(".")[2]))
            shown = alias.name + (f" as {alias.asname}" if alias.asname else "")
            if name is None:  # from . import module
                level, module = relative(new_name(target), new_pkg)
                parent, _, leaf = module.rpartition(".")
                groups.setdefault((level, parent), []).append(leaf + (f" as {alias.asname}" if alias.asname else ""))
            else:
                groups.setdefault(relative(new_name(target), new_pkg), []).append(shown)
        statements = [f"{indent}from {'.' * level}{module} import {', '.join(names)}\n" for (level, module), names in groups.items()]
        lines[node.lineno - 1 : node.end_lineno] = statements
    new_path.write_text("".join(lines))
print("moved and rewritten")
```

Then run it, `uv run ruff check --fix custom_components/pururu`, `uv run ruff format custom_components/pururu` (it re-wraps and re-sorts the regenerated lines), and read `git diff --stat`.

- [ ] **Step 3: Tests' module paths**

Replace, in `tests/*.py`: `module("reactions")` → `module("device_keys.reactions")`, `module("notifications")` → `module("device_keys.notifications")`, `module("feature")` → `module("core.feature")`, `module("entity")` → `module("core.entity")`, `module("messages")` → `module("core.messages")`, `module("generated")` → `module("core.generated")`, `module("files")` → `module("core.files")`, `module("alert_lights")` → `module("outputs.alert_lights")`, `module("places")` → `module("outputs.places")`, `module("dashboard")` → `module("outputs.dashboard")`, `module("lifecycle")` → `module("setup.lifecycle")`. In `tests/test_generated.py`, `Case` gains `module: str` (`"device_keys.reactions"`, `"device_keys.programs"`), used where it calls `module(case.source)`; `source` stays the log word.

- [ ] **Step 4: Sonar** — every `resourceKey=custom_components/pururu/<moved>.py` follows its file (`places.py` → `outputs/places.py`, `generated.py` → `core/generated.py`, `files.py` → `core/files.py`, `alert2_alerts.py` → `outputs/alert2_alerts.py`).

- [ ] **Step 5: Verify**

- `uv run pytest -q` → every test passes (1098).
- AST: for every moved module, `ast.dump` of the old file (`git show HEAD:<old path>`) and of the new one, both with `ImportFrom` nodes removed, are equal.
- Import each module first, in a fresh interpreter: `for m in <every module>: python -c "import importlib; importlib.import_module('custom_components.pururu.' + m)"` inside `uv run`, from the repo root; no error.

- [ ] **Step 6: Commit** — `git commit -m "pururu: one folder per layer: core, device_keys, outputs, setup (refactor A2-layout)"`

---

### Task 2: The import test by folder

**Files:** `tests/test_code.py`.

- [ ] **Step 1:** `CORE` becomes "every module under `core/`, and `const`"; `test_the_core_imports_only_the_core` walks `core/*.py`; the platforms may import only `core.runtime`. Watch each fail once (add `from ..setup import lifecycle` to `core/runtime.py`; `from .outputs import events` to `sensor.py`), restore, pass.
- [ ] **Step 2:** Commit `tests: the import rules by folder (refactor A2-layout)`.

---

### Task 3: Docs, coverage, review, PR

- [ ] **Step 1: Docs.** `CLAUDE.md` (Architecture: where the code lives, by folder), `docs/develop/index.mdx` (the layout tree), `docs/develop/architecture.mdx` and `writing-a-feature.mdx` where they name a moved module's file. `pnpm docs:check`.
- [ ] **Step 2: Coverage per function** (the A2a script): nothing lost.
- [ ] **Step 3: Local final review** of the whole branch by a fresh reviewer; fix its Critical and Important findings with tests; only then:
- [ ] **Step 4: PR** based on `refactor/a2a-lifecycle` (`pururu: refactor A2-layout, one folder per layer (0.2.0)`); retarget to `main` once #44 merges.
