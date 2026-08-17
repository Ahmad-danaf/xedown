"""Leak detection for the live probes.

`ledger` is pure and tested in CI. `hooks` imports `gi` and is only
importable inside a real xed process; nothing here imports it for you.
"""
