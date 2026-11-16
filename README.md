# zmp-injury-reports

Data feed for the **ZAYS MOTION PLAYS** dashboard (Sports Picks side).

- `reports/` — NFL injury reports, refreshed by a scheduled cloud task.
- `pick_log/picks_inbox.json` — the shared **JTAXXIN&ZAYS PICK LOG** inbox. jtaxxin and Zay send screenshots of their picks to Claude, and Claude adds them here. The dashboard (6.5+) syncs new picks every 2 minutes.

Rules for Claude are in [CLAUDE.md](CLAUDE.md). The 15-minute BTC side is not in this repo and isn't touched by anything here.
