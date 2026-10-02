# Issue dispatcher

Turns the issues you open and label `ready` into pull requests: one headless `lfg` session per issue, each in its own worktree, with labels showing where each one stands.

```sh
python3 tools/dispatcher/dispatcher.py run                          # 2 sessions at most, a poll every 5 minutes
python3 tools/dispatcher/dispatcher.py run --sessions 3 --every 120
python3 tools/dispatcher/dispatcher.py stop                         # ends a running dispatcher and every session, pausing each issue
uv run pytest tools -n 0 -q                                         # its tests
```

- `dispatcher.py`: the script (stdlib only).
- `tests/test_dispatcher.py`: its tests, collected by `uv run pytest` (`testpaths` in `pyproject.toml`).
- `.state/`: the sessions' logs, a record of each running session (`sessions/`) and the lock file (an flock, kept on disk), git-ignored.

Ctrl-C stops the dispatcher and leaves its sessions running: the next `run` follows them. How it works, the labels, the flags and `stop`: [docs/develop/dispatcher.mdx](../../docs/develop/dispatcher.mdx).
