
# E*TRADE Rotator — Qty Fix Build

This build includes:
- Robust quantity extraction in `etrade_api.py` (handles `orderedQuantity` and other alternates).
- GUI guard inside `_run_now` to prevent crashes when `qty` is missing, with a clear error message.

## How to run (macOS)
1. Double‑click `Run GUI.command`.
2. If blocked by Gatekeeper, right‑click → Open.

## Notes
If an order truly lacks a quantity, the GUI will show a friendly error. Use **Preview** again, or reselect a valid order.


## 2025-09-18
- Change Preview now uses HTTP PUT (with automatic POST fallback) for `/orders/{orderId}/change/preview.json` to avoid 405 responses on some E*TRADE tenants.


## No-Permissions Launcher
- Double-click **Launch App.py** on macOS or Windows to start without needing to chmod.
- Optional: **First Run.command** simply invokes the Python launcher if you prefer .command files.

- preview_change: PUT with POST fallback to avoid 405

- Fixed preview_change indentation and logic (PUT with POST fallback).
