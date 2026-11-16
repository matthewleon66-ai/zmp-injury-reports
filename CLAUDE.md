# Instructions for Claude (read before changing anything in this repo)

This repo feeds the **ZAYS MOTION PLAYS** dashboard (owner: Zay, GitHub `matthewleon66-ai`).
Partner **jtaxxin** helps with the **Sports Picks** side only.

## What lives here
| Path | What it is | Who changes it |
|---|---|---|
| `pick_log/picks_inbox.json` | Shared **JTAXXIN&ZAYS PICK LOG** inbox — sports picks only | jtaxxin's Claude or Zay's Claude |
| `reports/nfl_injury_reports.json` | NFL injury reports | Only the scheduled injury-report task |
| `README.md`, `CLAUDE.md` | Docs | Zay only |

## Hard rules
1. **Sports picks only.** Never add, change or suggest anything for the 15-minute BTC side of the dashboard (scalps, Zay Early Pick, Zay Lock, settlement, BRTI, Terry). That side is Zay's alone and is not in this repo.
2. **Only edit `pick_log/picks_inbox.json`** when adding picks. Do not touch `reports/` (unless you are the scheduled injury-report task), `README.md` or this file.
3. **Append only.** Add new entries to the END of `"picks"`. Never edit, reorder or delete existing entries — the dashboard adds each `id` once, so changing an old entry does nothing and deleting one breaks history. To grade or fix a pick, append a new `result` entry (below).
4. Every `id` must be new and unique. Use `jt-YYYYMMDD-HHMM-N` for jtaxxin's picks (e.g. `jt-20261116-1412-1`), `zay-YYYYMMDD-HHMM-N` for Zay's.
5. The file must stay valid JSON. Check it parses before committing.
6. Commit straight to `main` with a message like `Pick: jtaxxin — BAL ML 62¢ Kalshi`. The dashboard picks it up within about 2 minutes.

## Reading a screenshot
When jtaxxin (or Zay) sends a screenshot of a bet slip or open position from **Novig, Polymarket or Kalshi**:
- One entry per single bet; one `parlay` entry per parlay (with every leg).
- Read the book from the app's look/name. If unsure, ask.
- Price: for Polymarket/Kalshi use the cents paid (`entry_cents`, 1–99). For odds (Novig or a parlay), use `odds` like `"+450"` or `"-120"`.
- Include `stake` (dollars risked) and `to_win` if the screenshot shows them.
- `date` = the game date (YYYY-MM-DD), not today's date if different.
- If anything is unreadable (team, price, stake), ask instead of guessing.
- After adding, reply with a short list of what you added so he can double-check.

## Single pick format
```json
{
  "id": "jt-20261116-1412-1",
  "by": "JTAXXIN",
  "type": "single",
  "league": "NFL",
  "team": "Baltimore Ravens",
  "opponent": "Los Angeles Chargers",
  "bet": "ML",
  "label": "",
  "book": "Kalshi",
  "entry_cents": 62,
  "odds": null,
  "stake": 20,
  "to_win": 12.26,
  "date": "2026-11-16",
  "note": "from screenshot"
}
```
- `by`: `"JTAXXIN"` or `"ZAY"` — whose pick it is.
- `league`: one of `NFL`, `NBA`, `CFB`, `MLB`, `NHL`, `MLS`, `EPL`.
- `team` / `opponent`: full team names as the dashboard shows them (ESPN names, e.g. "Los Angeles Chargers").
- `bet`: `"ML"` for moneyline / winner (graded automatically). Anything else (spread, total, prop) → `"OTHER"` and put the bet in `label`, e.g. `"BAL -3.5"`, `"O 44.5"`. Those need a result entry later.
- `book`: `"Novig"`, `"Polymarket"` or `"Kalshi"`.

## Parlay format
```json
{
  "id": "jt-20261116-1415-1",
  "by": "JTAXXIN",
  "type": "parlay",
  "book": "Novig",
  "odds": "+450",
  "stake": 10,
  "to_win": 45,
  "note": "from screenshot",
  "legs": [
    {"league": "NBA", "team": "LA Clippers", "opponent": "Los Angeles Lakers", "bet": "ML", "date": "2026-11-16"},
    {"league": "NFL", "team": "Baltimore Ravens", "opponent": "Los Angeles Chargers", "bet": "OTHER", "label": "BAL -3.5", "date": "2026-11-16"}
  ]
}
```

## Grading a pick (spreads, totals, props, or a fix)
Moneyline picks grade themselves from the final score. For anything else, append:
```json
{"id": "jt-20261117-0900-r1", "action": "result", "target": "jt-20261116-1412-1", "result": "WIN"}
```
- `result`: `WIN`, `LOSS` or `PUSH`.
- For one parlay leg add `"leg": 0` (0 = first leg). The parlay's result updates from its legs.
