#!/usr/bin/env python3
"""
Interactive name-pair reviewer
==============================
Works through outputs/name_review_candidates.csv one pair at a time, shows
context from the raw data so you can make an informed call, and saves each
decision immediately to outputs/name_decisions.csv.

Resumes from where you left off — already-decided pairs are skipped.

Usage:
    python3 review_names.py                       # review all undecided pairs
    python3 review_names.py --status              # show progress summary
    python3 review_names.py --undo                # undo your last decision
"""
import argparse, csv, sys
from pathlib import Path
import pandas as pd

CANDIDATES = Path("outputs/name_review_candidates.csv")
DECISIONS  = Path("outputs/name_decisions.csv")
DATA_CSV   = Path("Mission_Ignite_Data.csv")

NORTHSTAR_COLS = [
    "Assessment ID", "User Name", "User Email", "Topic", "Software Version",
    "Legacy vs New", "Start", "End", "Duration (h:mm:ss)",
    "Duration (mins)", "Duration (seconds)", "Num Correct", "Num Possible",
    "Score Percentage", "Passed", "Proctored",
    "Proctor", "Northstar Location", "Tags",
]

VALID_ANSWERS = {"y", "yes", "n", "no", "s", "skip", "q", "quit"}


# ── helpers ──────────────────────────────────────────────────────────────────

def load_work():
    raw = pd.read_csv(DATA_CSV, header=None, dtype=str)
    raw.columns = NORTHSTAR_COLS[:len(raw.columns)]
    raw = raw[raw["Score Percentage"] != "Score Percentage"].copy()
    raw["name_key"] = raw["User Name"].str.strip().str.lower().str.replace(
        r"[^\w\s'-]", "", regex=True
    ).str.replace(r"\s+", " ", regex=True)
    raw["phase"] = raw["Tags"].apply(_parse_phase)
    raw["Start"] = pd.to_datetime(raw["Start"], errors="coerce", utc=True)
    return raw


def _parse_phase(tags):
    if not isinstance(tags, str):
        return "unknown"
    t = tags.lower()
    pre, post = "pre" in t, "post" in t
    if post and not pre:
        return "post"
    if pre and not post:
        return "pre"
    return "ambiguous" if (pre and post) else "unknown"


def load_decisions():
    if not DECISIONS.exists():
        return {}
    decisions = {}
    with open(DECISIONS, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["name_a"].strip(), row["name_b"].strip())
            decisions[key] = row["decision_same_person?"].strip()
    return decisions


def save_decision(name_a, name_b, similarity, decision):
    write_header = not DECISIONS.exists()
    with open(DECISIONS, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["name_a", "name_b", "similarity", "decision_same_person?"])
        w.writerow([name_a, name_b, similarity, decision])


def undo_last():
    if not DECISIONS.exists():
        print("No decisions file yet — nothing to undo.")
        return
    lines = DECISIONS.read_text(encoding="utf-8").splitlines()
    if len(lines) <= 1:
        print("No decisions to undo.")
        return
    removed = lines[-1]
    DECISIONS.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    print(f"Undone: {removed}")


def context_block(name_key, work, label):
    rows = work[work["name_key"] == name_key]
    n = len(rows)
    if n == 0:
        return f"  {label}: (no records found)"
    sites    = rows["Tags"].dropna().apply(_parse_site).value_counts().index.tolist()
    topics   = sorted(rows["Topic"].dropna().unique())
    phases   = rows["phase"].value_counts().to_dict()
    dates    = rows["Start"].dropna()
    date_rng = ""
    if len(dates):
        mn = dates.min().strftime("%Y-%m-%d")
        mx = dates.max().strftime("%Y-%m-%d")
        date_rng = f"{mn} – {mx}" if mn != mx else mn
    # sample display names
    sample_names = rows["User Name"].dropna().unique()[:3]

    lines = [
        f"  {label}  ({n} records):",
        f"    Names seen : {', '.join(sample_names)}",
        f"    Sites      : {', '.join(sites[:4]) or '—'}",
        f"    Topics     : {', '.join(topics[:5])}" + (" …" if len(topics) > 5 else ""),
        f"    Phases     : " + "  ".join(f"{k}={v}" for k, v in phases.items()),
        f"    Dates      : {date_rng or '—'}",
    ]
    return "\n".join(lines)


def _parse_site(tags):
    import re
    PHASE_TOKENS = {"preassessment", "postassessment", "pre", "post"}
    REVIEWER_RE  = re.compile(r"reviewed", re.I)
    SEASON_RE    = re.compile(r"(spring|summer|fall|autumn|winter)\b", re.I)
    YEAR_RE      = re.compile(r"\b(19|20)\d{2}\b")
    if not isinstance(tags, str) or not tags.strip():
        return "Unknown"
    for part in tags.split(","):
        p, low = part.strip(), part.strip().lower()
        if not p or low in PHASE_TOKENS or REVIEWER_RE.search(low):
            continue
        stripped = YEAR_RE.sub("", SEASON_RE.sub("", low)).strip(" -")
        if not stripped:
            continue
        return p
    return "Unknown"


def show_status(candidates, decisions):
    total = len(candidates)
    decided = len(decisions)
    yes = sum(1 for v in decisions.values() if v.lower() in ("y", "yes"))
    no  = sum(1 for v in decisions.values() if v.lower() in ("n", "no"))
    skipped = decided - yes - no
    remaining = total - decided
    print(f"\nProgress: {decided}/{total} decided  ({remaining} remaining)")
    print(f"  Yes (same person): {yes}")
    print(f"  No               : {no}")
    print(f"  Skipped          : {skipped}")
    if remaining == 0:
        print("\nAll pairs reviewed!")
        print(f"Run the engine with confirmed merges:")
        print(f"  python3 match_and_measure.py Mission_Ignite_Data.csv --outdir outputs")
    else:
        print(f"\nResume: python3 review_names.py")


# ── main review loop ──────────────────────────────────────────────────────────

def review(start_at=None):
    if not CANDIDATES.exists():
        print(f"ERROR: {CANDIDATES} not found. Run the engine first:")
        print("  python3 match_and_measure.py Mission_Ignite_Data.csv --outdir outputs")
        sys.exit(1)

    candidates = pd.read_csv(CANDIDATES)
    decisions  = load_decisions()
    work       = load_work()

    total     = len(candidates)
    undecided = [
        row for _, row in candidates.iterrows()
        if (row["name_a"], row["name_b"]) not in decisions
    ]
    n_undecided = len(undecided)

    if n_undecided == 0:
        print("All pairs already decided.")
        show_status(candidates, decisions)
        return

    if start_at:
        # fast-forward to a specific pair number (1-based among undecided)
        idx = int(start_at) - 1
        undecided = undecided[idx:]

    done_this_session = 0

    print(f"\n{'='*62}")
    print(f"NAME PAIR REVIEW  ({n_undecided} undecided of {total} total)")
    print(f"{'='*62}")
    print("Keys: y=yes  n=no  s=skip  q=quit")
    print("      (decisions auto-saved; resume anytime)\n")

    for i, row in enumerate(undecided, 1):
        na, nb, sim = row["name_a"], row["name_b"], row["similarity"]
        position = total - n_undecided + i  # absolute position for display

        print(f"\n[{position}/{total}]  similarity={sim:.1f}%")
        print(f"  A: {na}")
        print(f"  B: {nb}")
        print(context_block(na, work, "A"))
        print(context_block(nb, work, "B"))
        print()

        while True:
            try:
                ans = input("  Same person? [y/n/s=skip/q=quit] > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nInterrupted — progress saved.")
                show_status(candidates, decisions)
                return

            if ans not in VALID_ANSWERS:
                print("  Please enter y, n, s, or q.")
                continue

            if ans in ("q", "quit"):
                print("\nQuitting — progress saved.")
                show_status(candidates, decisions)
                return

            if ans in ("s", "skip"):
                # Don't record skips permanently so you can revisit them later
                print("  Skipped.")
                break

            decision = "y" if ans in ("y", "yes") else "n"
            save_decision(na, nb, sim, decision)
            decisions[(na, nb)] = decision
            done_this_session += 1
            label = "YES — will merge" if decision == "y" else "NO"
            print(f"  Saved: {label}")
            break

    print(f"\nSession complete. Reviewed {done_this_session} new pairs this session.")
    show_status(candidates, load_decisions())

    yes_count = sum(1 for v in load_decisions().values() if v.lower() in ("y", "yes"))
    if yes_count:
        print(f"\nWhen ready to apply {yes_count} confirmed merge(s), run:")
        print(f"  python3 match_and_measure.py Mission_Ignite_Data.csv --outdir outputs")
        print(f"  (the engine auto-reads outputs/name_decisions.csv)")


def main():
    ap = argparse.ArgumentParser(description="Review fuzzy name pairs for Mission: Ignite data.")
    ap.add_argument("--status", action="store_true", help="show review progress and exit")
    ap.add_argument("--undo",   action="store_true", help="undo last decision and exit")
    ap.add_argument("--start",  metavar="N", help="start at undecided pair number N (1-based)")
    a = ap.parse_args()

    if a.undo:
        undo_last()
        return
    if a.status:
        if not CANDIDATES.exists():
            print("No candidates file yet. Run the engine first.")
            return
        show_status(pd.read_csv(CANDIDATES), load_decisions())
        return

    review(start_at=a.start)


if __name__ == "__main__":
    main()
