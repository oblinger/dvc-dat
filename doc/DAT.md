---
cab-traits: [Code]
description: "dvc-dat — data artifacts with metadata and provenance for ML experimentation"
---

| -[[DAT]]-                 | : doc — dvc-dat — data artifacts with metadata and provenance for ML experimentation<br>→ [DAT](ha://p/DAT)  (grove/dvc-dat/doc)                                                                                                                                               |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Pin**                   | [[DAT030 - A dat is its functional content every execution a run record inside it, outside the hash\|F030]],                                                                                                                                                                   |
| External                  | [Repo](https://github.com/oblinger/dvc-dat) · Code: `~/ob/grove/dvc-dat/` (Python `dvc_dat/`, `docs/`, `tests/`) · [Docs](https://github.com/oblinger/dvc-dat/blob/main/docs/index.md)                                                                                         |
| [[DAT Design\|Design]]+   | [[DAT Architecture.svg\|Architecture.svg]],                                                                                                                                                                                                                                    |
| [[DAT Track\|Plan]]+      | [[DAT Backlog\|Backlog]],  [[DAT Inbox\|Inbox]],  [[DAT Pebbles\|Pebbles]],  [[DAT Messages\|Messages]],  [[DAT queries\|queries]],  [[DAT Responses\|Responses]],                                                                                                             |
| [[DAT Archive\|Archive]]+ | [[DAT Interface\|Interface]],                                                                                                                                                                                                                                                  |
| Consumers                 | [[SVP]],                                                                                                                                                                                                                                                                       |
| Data (2024)               | [Data Game Master List](hook://Data%20Game%20Master%20List),  [Data Game Tracking](hook://Data%20Game%20Tracking),  [Data Games](hook://Data%20Games),  [Data Tasks](hook://Data%20Tasks),  [Dataset](hook://Dataset),  [Nutrition Data Page](hook://Nutrition%20Data%20Page), |
| ...                       |                                                                                                                                                                                                                                                                                |

# DAT — dvc-dat, the data-artifact layer
`dvc_dat` gives a folder of data a `_spec_.yaml` (metadata, provenance, how it was made) and gives Python a dotted-name namespace (`do.load("catalog.experiment")`) configured by `.datconfig.yaml` mounts. Public on GitHub, version 1.2.0, 75 tests. The agent DAT owns the repo; consumers ([[SVP]] first) file what they need in [[DAT Inbox]]. Operating rules: this folder's `CLAUDE.md`.

## Plan 2024-10 (historical — the SV alg2 metrics round)

Make updates directly in DAT-DVC.
- Assume dat.py is pulled into our alg2
- [ ] Use TOML file for location of data folder
- fixes: register abstrct class method, use fn doc string
- [ ] = Juan assesses dat.py & metrics.py (propose edits)
- [ ] = Fresh metric branch w/ DAT imported
- [ ] Dan updates dat & adds metrics => Runs game metrics on Norm1
- [ ] Juan adds shot metric types => Basic game stats
- [ ] PR
- [ ] Martin Homo-metric-type; Greg adds shot & game metrics
- [ ] $ stat

## Todo (historical)

- [ ] Implement Lazy Dat.loading
- [ ] Implement multi-runner
- [x] Update mount docs; command
- [x] test nu mount
- [ ] See if system works
- [ ] Folder of video files into DatContainer with Dat per file

## History

- 2026-09-21 — Stood up as an agent-owned code anchor ([[Atticus Backlog#^T410|ATT T410]]): slug `DAT`, `DAT Track/` with Backlog, Inbox and Pebbles, this page's masthead rebuilt, `CLAUDE.md` written. Dan: *"Should I have an agent in charge of DAT? … we can easily create one."* Reason: a public repo about to take a semantics change for [[SVP]] needs an owner whose interest is the repo and its every consumer. The 2024 plan and todo above are kept as history, not live work — anything still wanted becomes a Backlog row.
