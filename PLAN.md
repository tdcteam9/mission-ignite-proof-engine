# PLAN — Who does what, and in what order

Team of 4. Two tracks run in parallel and meet at one folder: `outputs/`.
Code produces the trusted numbers; Cowork turns them into the seven submissions.

## 0. What the 85% bar means (read first)
The assessments serve THREE purposes, and the engine now serves all three:
1. **Prove learning** — community learners' pre → post gains.
2. **Qualify trainers** — 85% is the bar to be trainer-eligible, so a learner who clears 85% is
   also a trainer-eligible graduate. The data already holds a trainer-applicant pool (records tagged
   "M:I Staff/AmeriCorps Volunteers / Pre-Employment"); the engine reports their qualification rate
   separately in `centers.json`. **Team must confirm this tag = trainer applicants.**
3. **Rank centers** — the tagged site (e.g. Orleans CCCE) is the center/trainer delivering training.
   The engine ranks centers on two honest lenses (value added vs absolute outcome) so centers serving
   harder-starting learners aren't unfairly penalized.

## Roles

**P1 — Engineer (Claude Code).** Owns the engine and the numbers.
- Day 1: clone this folder, `pip install -r requirements.txt`, run the engine + dashboard (commands below). Confirm the numbers reproduce.
- Day 1–2: work the `name_review_candidates.csv` (390 pairs) — decide same-person Y/N, feed confirmed merges back so more pre-only/post-only records pair up. Clean `unresolved_sites.csv` into a small site lookup.
- Day 2–3: freeze the engine, write the plain-English "How it works" notes (Deliverable #1) describing person-vs-computer steps. Copilot is fine for boilerplate; keep the matching logic on Claude.

**P2 — Designer (Cowork + PowerPoint/Design).** Owns the two reports + deck visuals.
- Needs only `outputs/summary.json` + `dashboard.html`. Starts Day 1 with current numbers, refreshes when P1 freezes.
- Builds Deliverable #3: funder one-pager (benchmark + gain, N on every figure, no names) and site-staff report (per-site framing). Then leads deck visuals (#7).

**P3 — Marketer (Cowork + Claude in Chrome).** Owns growth.
- Needs `summary.json` only. Builds Deliverable #4: 3 example posts using aggregate, name-free results + a consent/dignity workflow for featuring a learner. Uses Chrome to study how comparable nonprofits post results.

**P4 — PM / Writer (Cowork; Gemini for fast drafts).** Owns the words + assembly.
- Deliverable #5 user guide (non-technical, "drop export here, click run, who sees what"), #6 sustainability plan (cost, lean-team fit, hand-off after staff leave), and owns final submission assembly + the 3–5 min pitch script (#7).

## Sequencing (one week)
1. **All, Day 1 (30 min):** agree two design calls — fuzzy-match strictness (false matches vs missed reunions) and a minimum-N before a site shows publicly.
2. **P1** gets engine reproducing + review list out → unblocks everyone.
3. **P2/P3** start on current numbers immediately; **P4** drafts guide/sustainability in parallel.
4. **Mid-week:** P1 freezes numbers → P2/P3 refresh final figures.
5. **End of week:** P4 assembles all 7, team rehearses pitch.

## The two design calls to make together (these decide your score)
- **Matching strictness:** stricter = fewer but unimpeachable matches; looser = more coverage, more risk. Recommendation: stay exact-name for headline numbers, use the review list to add only human-confirmed merges.
- **Public site threshold:** don't publish a site's results below e.g. N=10 — protects small sites and keeps numbers honest.
- **Confirm the trainer-applicant tag:** verify that "M:I Staff/AmeriCorps Volunteers / Pre-Employment" records are trainer applicants. If yes, the trainer-pipeline report is a real leadership/HR deliverable; if not, fold those records back into the relevant population.
