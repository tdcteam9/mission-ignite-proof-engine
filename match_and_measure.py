#!/usr/bin/env python3
"""
Mission: Ignite -- Proof Engine (prototype v2)
==============================================
Turns raw Northstar assessment exports into trustworthy, defensible proof of learning.
Answers the brief's core question -- "who actually learned, where, and by how much" --
and attaches a real headcount to every number so it survives a funder meeting.

Three hard questions (from the brief) -> three design choices:
  1. MATCH THE RIGHT PEOPLE   -> deterministic name key + (person, topic) pairing.
                                 Near-duplicate names are SURFACED for human review,
                                 never silently merged. No invented matches.
  2. NUMBERS THAT HOLD UP     -> every metric carries N (distinct people). Same-phase
                                 duplicates collapsed by an explicit, stated rule and flagged.
  3. SUSTAIN ON A LEAN TEAM   -> one command, same result every cycle, no spreadsheet wrangling.

Usage:
    python match_and_measure.py /path/to/Mission_Ignite_Data.csv --outdir outputs
"""
import argparse, csv, json, re
from pathlib import Path
import pandas as pd, numpy as np
import weak_points as wp
import center_analysis as ca

# Northstar Digital Literacy Assessment export column names.
# The raw export has no header on the first row; a duplicate header row may appear
# mid-file when two exports are concatenated. We detect and strip it below.
NORTHSTAR_COLS = [
    "Assessment ID", "User Name", "User Email", "Topic", "Software Version",
    "Legacy vs New", "Start", "End", "Duration (h:mm:ss)",
    "Duration (mins)", "Duration (seconds)", "Num Correct", "Num Possible",
    "Score Percentage", "Passed", "Proctored",
    "Proctor", "Northstar Location", "Tags",
]

try:
    from rapidfuzz import fuzz, process
    HAVE_FUZZ = True
except ImportError:
    HAVE_FUZZ = False

BENCHMARK = 85.0  # confirmed: Passed == (Score Percentage >= 85.0)
FUZZ_REVIEW_MIN = 90   # surface name pairs >= this similarity for human review
PHASE_TOKENS = {"preassessment", "postassessment", "pre", "post"}
SEASON_RE = re.compile(r"(spring|summer|fall|autumn|winter)\b", re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
REVIEWER_RE = re.compile(r"reviewed", re.I)

def normalize_name(raw):
    if not isinstance(raw, str): return ""
    s = re.sub(r"[^\w\s'-]", "", raw.strip().lower())
    return re.sub(r"\s+", " ", s)

def parse_phase(tags):
    if not isinstance(tags, str): return "unknown"
    t = tags.lower(); pre, post = "pre" in t, "post" in t
    if post and not pre: return "post"
    if pre and not post: return "pre"
    if pre and post: return "ambiguous"
    return "unknown"

def parse_site(tags):
    if not isinstance(tags, str) or not tags.strip(): return "Unknown site"
    for part in tags.split(","):
        p, low = part.strip(), part.strip().lower()
        if not p or low in PHASE_TOKENS or REVIEWER_RE.search(low): continue
        stripped = YEAR_RE.sub("", SEASON_RE.sub("", low)).strip(" -")
        if not stripped: continue
        return p
    return "Unknown site"

def build_pairs(df):
    work = df.copy()
    work["name_key"] = work["User Name"].map(normalize_name)
    work["phase"]    = work["Tags"].map(parse_phase)
    work["site"]     = work["Tags"].map(parse_site)
    work["Start"]    = pd.to_datetime(work["Start"], errors="coerce", utc=True)
    usable = work[work["phase"].isin(["pre", "post"])].copy()

    pairs, ambiguous = [], 0
    for (name, topic), grp in usable.groupby(["name_key", "Topic"]):
        pres  = grp[grp.phase == "pre"].sort_values("Start")
        posts = grp[grp.phase == "post"].sort_values("Start")
        if len(pres) == 0 or len(posts) == 0: continue
        multi = len(pres) > 1 or len(posts) > 1
        if multi: ambiguous += 1
        pre, post = pres.iloc[0], posts.iloc[-1]   # earliest pre, latest post
        pairs.append({
            "name_key": name, "display_name": pre["User Name"], "topic": topic,
            "site": pre["site"] if pre["site"] != "Unknown site" else post["site"],
            "pre_score": pre["Score Percentage"], "post_score": post["Score Percentage"],
            "gain": round(post["Score Percentage"] - pre["Score Percentage"], 2),
            "post_passed": post["Score Percentage"] >= BENCHMARK,
            "pre_date": pre["Start"].date().isoformat() if pd.notna(pre["Start"]) else None,
            "post_date": post["Start"].date().isoformat() if pd.notna(post["Start"]) else None,
            "match_confidence": "exact-name",          # only deterministic matches counted
            "multi_record_flag": multi,
        })
    pairs_df = pd.DataFrame(pairs)
    audit = {
        "total_records": int(len(work)),
        "usable_pre_post_records": int(len(usable)),
        "records_phase_unknown": int((work.phase == "unknown").sum()),
        "records_phase_ambiguous": int((work.phase == "ambiguous").sum()),
        "distinct_learners_normalized": int(work.name_key.nunique()),
        "raw_name_spellings": int(work["User Name"].nunique()),
        "matched_pairs": int(len(pairs_df)),
        "distinct_people_with_a_pair": int(pairs_df.name_key.nunique()) if len(pairs_df) else 0,
        "ambiguous_cells_resolved_by_rule": int(ambiguous),
        "fuzzy_available": HAVE_FUZZ,
    }
    return pairs_df, work, audit

def fuzzy_review(work, outdir):
    """Surface near-duplicate name keys for a HUMAN to confirm. Never auto-merged."""
    if not HAVE_FUZZ: return 0
    names = sorted(work.name_key.dropna().unique())
    seen, rows = set(), []
    for n in names:
        for match, score, _ in process.extract(n, names, scorer=fuzz.token_sort_ratio, limit=4):
            if match == n: continue
            key = tuple(sorted((n, match)))
            if key in seen or score < FUZZ_REVIEW_MIN: continue
            seen.add(key)
            rows.append({"name_a": key[0], "name_b": key[1], "similarity": round(score, 1),
                         "decision_same_person?": ""})
    pd.DataFrame(rows).sort_values("similarity", ascending=False).to_csv(
        outdir / "name_review_candidates.csv", index=False)
    return len(rows)

def summarize(p):
    if len(p) == 0: return {"note": "no matched pairs"}
    def block(d):
        return {"n_pairs": int(len(d)), "n_people": int(d.name_key.nunique()),
                "mean_pre": round(d.pre_score.mean(), 1), "mean_post": round(d.post_score.mean(), 1),
                "mean_gain": round(d.gain.mean(), 1), "median_gain": round(d.gain.median(), 1),
                "pct_reaching_benchmark_post": round(100 * d.post_passed.mean(), 1),
                "n_reaching_benchmark_post": int(d.post_passed.sum()),
                "n_improved": int((d.gain > 0).sum()), "pct_improved": round(100 * (d.gain > 0).mean(), 1)}
    overall = block(p)
    buckets = pd.cut(p.gain, [-1e3, -.01, 9.99, 24.99, 49.99, 1e3],
                     labels=["declined", "0-10", "10-25", "25-50", "50+"])
    overall["gain_distribution"] = {str(k): int(v) for k, v in buckets.value_counts().items()}
    return {"overall": overall,
            "by_topic": {t: block(g) for t, g in p.groupby("topic")},
            "by_site":  {s: block(g) for s, g in p.groupby("site")}}

def load_confirmed_merges(merges_path):
    """Read name_decisions.csv and return a dict mapping each confirmed name to its canonical."""
    path = Path(merges_path)
    if not path.exists():
        return {}, 0
    confirmed = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dec = row.get("decision_same_person?", "").strip().lower()
            if dec in ("y", "yes"):
                confirmed.append((row["name_a"].strip(), row["name_b"].strip()))
    if not confirmed:
        return {}, 0

    # Union-Find so transitive merges collapse to one canonical
    parent = {}

    def find(x):
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a, b):
        pa, pb = find(a), find(b)
        if pa != pb:
            # canonical = alphabetically first for determinism
            if pa < pb:
                parent[pb] = pa
            else:
                parent[pa] = pb

    for a, b in confirmed:
        union(a, b)

    remap = {n: find(n) for n in parent if find(n) != n}
    return remap, len(confirmed)


def apply_merges_to_work(work_df, remap):
    """Remap name_keys in-place according to confirmed merges."""
    if not remap:
        return work_df
    w = work_df.copy()
    w["name_key"] = w["name_key"].map(lambda n: remap.get(n, n))
    return w


def build_pairs_from_work(work, confidence_label="exact-name"):
    """Core pair-building logic operating on an already-enriched work DataFrame."""
    usable = work[work["phase"].isin(["pre", "post"])].copy()
    pairs, ambiguous = [], 0
    for (name, topic), grp in usable.groupby(["name_key", "Topic"]):
        pres  = grp[grp.phase == "pre"].sort_values("Start")
        posts = grp[grp.phase == "post"].sort_values("Start")
        if len(pres) == 0 or len(posts) == 0:
            continue
        multi = len(pres) > 1 or len(posts) > 1
        if multi:
            ambiguous += 1
        pre, post = pres.iloc[0], posts.iloc[-1]
        pairs.append({
            "name_key": name, "display_name": pre["User Name"], "topic": topic,
            "site": pre["site"] if pre["site"] != "Unknown site" else post["site"],
            "pre_score": pre["Score Percentage"], "post_score": post["Score Percentage"],
            "gain": round(post["Score Percentage"] - pre["Score Percentage"], 2),
            "post_passed": post["Score Percentage"] >= BENCHMARK,
            "pre_date": pre["Start"].date().isoformat() if pd.notna(pre["Start"]) else None,
            "post_date": post["Start"].date().isoformat() if pd.notna(post["Start"]) else None,
            "match_confidence": confidence_label,
            "multi_record_flag": multi,
        })
    return pd.DataFrame(pairs), ambiguous


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv"); ap.add_argument("--outdir", default="outputs")
    ap.add_argument("--items", default=None,
                    help="optional future item/question-level CSV; enables skill-level weak points")
    ap.add_argument("--merges", default=None,
                    help="path to name_decisions.csv with confirmed same-person decisions "
                         "(default: <outdir>/name_decisions.csv)")
    a = ap.parse_args(); outdir = Path(a.outdir); outdir.mkdir(parents=True, exist_ok=True)

    # --- load data ---
    # The Northstar export has no header on the first row. When two exports are
    # concatenated the column-name row reappears mid-file; strip those rows.
    raw = pd.read_csv(a.csv, header=None, dtype=str)
    raw.columns = NORTHSTAR_COLS[:len(raw.columns)]
    raw = raw[raw["Score Percentage"] != "Score Percentage"].copy()
    raw["Score Percentage"] = pd.to_numeric(raw["Score Percentage"], errors="coerce")
    raw["Start"] = pd.to_datetime(raw["Start"], errors="coerce", utc=True)
    df = raw

    # --- base build (exact-name matches only) ---
    pairs_df, work, audit = build_pairs(df)

    # --- apply confirmed human merges (if any) ---
    merges_path = Path(a.merges) if a.merges else outdir / "name_decisions.csv"
    remap, n_confirmed = load_confirmed_merges(merges_path)
    if n_confirmed:
        # Remap name_keys in work df, then rebuild pairs for the merged names only.
        # Records already paired by exact-name keep their original pair; we add new
        # pairs that only become possible once names are merged.
        work_m = work.copy()
        work_m["name_key"] = work_m["name_key"].map(lambda n: remap.get(n, n))
        new_pairs, _ = build_pairs_from_work(work_m, confidence_label="merge-confirmed")
        # Keep existing exact-name pairs; fill in new ones that didn't exist before
        existing_keys = set(zip(pairs_df["name_key"], pairs_df["topic"]))
        added = new_pairs[
            ~new_pairs.apply(lambda r: (r["name_key"], r["topic"]) in existing_keys, axis=1)
        ]
        pairs_df = pd.concat([pairs_df, added], ignore_index=True)
        work = work_m  # downstream analysis uses merged name_keys
        audit["confirmed_merges_applied"] = n_confirmed
        audit["new_pairs_from_merges"] = int(len(added))
        audit["matched_pairs"] = int(len(pairs_df))
        audit["distinct_people_with_a_pair"] = (
            int(pairs_df.name_key.nunique()) if len(pairs_df) else 0
        )

    summary = summarize(pairs_df)
    n_review = fuzzy_review(work, outdir)
    audit["name_review_candidates"] = n_review
    # unresolved sites for human cleanup
    work.loc[work.site == "Unknown site", ["Tags"]].drop_duplicates().to_csv(
        outdir / "unresolved_sites.csv", index=False)
    pairs_df.to_csv(outdir / "matched_pairs.csv", index=False)
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2))
    (outdir / "audit.json").write_text(json.dumps(audit, indent=2))

    # --- weak points: topic-level always; skill-level if a future items file is given ---
    weak = {"topic_level": wp.topic_weak_points(pairs_df)}
    if a.items:
        weak["skill_level"] = wp.item_weak_points(a.items, work)
    else:
        weak["skill_level"] = {"available": False,
                               "reason": "no items file supplied (standard export is topic-level only)"}
    (outdir / "weak_points.json").write_text(json.dumps(weak, indent=2))

    # --- centers & trainer pipeline ---
    centers = {
        "center_leaderboard": ca.center_leaderboard(pairs_df, work),
        "trainer_pipeline": ca.trainer_pipeline(work),
    }
    (outdir / "centers.json").write_text(json.dumps(centers, indent=2))
    o = summary["overall"]
    print("=" * 62)
    print("MISSION: IGNITE PROOF ENGINE v2 -- run complete")
    print("=" * 62)
    print(f"Records in:                  {audit['total_records']:,}")
    print(f"Distinct learners (est.):    {audit['distinct_learners_normalized']:,}")
    print(f"Matched pre->post pairs:     {audit['matched_pairs']:,}  "
          f"({'exact-name' if not n_confirmed else f'exact-name + {n_confirmed} confirmed merges'})")
    if n_confirmed:
        print(f"  New pairs from merges:     {audit.get('new_pairs_from_merges', 0):,}")
    print(f"Distinct people with a pair: {audit['distinct_people_with_a_pair']:,}")
    print(f"Unknown-phase records:       {audit['records_phase_unknown']:,}  (excluded, reported)")
    print(f"Ambiguous cells (resolved):  {audit['ambiguous_cells_resolved_by_rule']:,}")
    print(f"Name pairs to review:        {n_review:,}  -> name_review_candidates.csv")
    print("-" * 62)
    print(f"Mean gain:  +{o['mean_gain']} pts (n={o['n_people']})   "
          f"Improved: {o['pct_improved']}% ({o['n_improved']})   "
          f"Reached 85%: {o['pct_reaching_benchmark_post']}% ({o['n_reaching_benchmark_post']})")
    wpt = weak["topic_level"].get("by_outcome_worst_first", [])
    if wpt:
        worst = wpt[0]
        print(f"Weakest topic (outcome):     {worst['topic']} -- "
              f"{worst['pct_below_benchmark_after_training']}% still below 85% after training "
              f"(n={worst['people']})")
    print(f"Skill-level weak points:     "
          f"{'ENABLED (items file)' if weak['skill_level'].get('available') else 'ready when item-level data is provided'}")
    lb = centers["center_leaderboard"].get("by_absolute_outcome", [])
    if lb:
        top = lb[0]
        print(f"Top center (% reaching 85%): {top['center']} -- {top['pct_reaching_85']}% "
              f"({top['n_trainer_eligible']}/{top['learners']} trainer-eligible)")
    tp = centers["trainer_pipeline"]
    if tp.get("available"):
        print(f"Trainer applicants detected:  {tp['distinct_applicants']} people "
              f"({tp['total_applicant_records']} records) -- confirm tag with team")
    print(f"Outputs -> {outdir}/")

if __name__ == "__main__":
    main()
