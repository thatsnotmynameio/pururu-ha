# Issue dispatcher

Turns the issues you open and label `ready` into pull requests: one headless `lfg` session per issue, each in its own worktree, with labels showing where each one stands.

```sh
python3 tools/dispatcher/dispatcher.py run                          # 2 sessions at most, a poll every 5 minutes
python3 tools/dispatcher/dispatcher.py run --sessions 3 --every 120
uv run pytest tools -n 0 -q                                         # its tests
```

- `dispatcher.py`: the script (stdlib only).
- `test_dispatcher.py`: its tests, collected by `uv run pytest` (`testpaths` in `pyproject.toml`).
- `.state/`: logs and the lock while it runs, git-ignored.

How it works, the labels and the flags: [docs/develop/dispatcher.mdx](../../docs/develop/dispatcher.mdx).
