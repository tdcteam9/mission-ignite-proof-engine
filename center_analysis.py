#!/usr/bin/env python3
"""
Center & Trainer analysis
=========================
The 85% benchmark has TWO real-world meanings at Mission: Ignite:
  (a) proof a community learner gained the skill, and
  (b) the qualification bar to become a digital-skills trainer.
The tagged site of an assessment is the CENTER / trainer delivering the program
(e.g. "Orleans CCCE"). This module ranks centers and tracks the trainer pipeline.

Two functions:
  center_leaderboard() -- ranks community centers by learner outcomes, on TWO honest
      lenses so centers serving harder-starting populations aren't unfairly penalized:
        - absolute outcome : % of learners reaching the 85% bar (= trainer-eligible)
        - value added      : mean gain (points moved)
      Trainer-applicant records and unknown sites are excluded; min-N protects small centers.

  trainer_pipeline() -- isolates trainer applicants (records tagged staff / AmeriCorps /
      volunteer / pre-employment) and reports, per topic, how many distinct applicants
      cleared the 85% qualification bar. ** Team: confirm this tag = trainer applicants. **
"""
import pandas as pd, numpy as np

BENCHMARK = 85.0
TRAINER_APPLICANT_PAT = r"staff|americorps|volunteer|pre-employment|pre employment"


def center_leaderboard(pairs_df, work_df, min_n=10):
    if len(pairs_df) == 0:
        return {"note": "no matched pairs"}
    # exclude trainer-applicant sites and unknown sites from COMMUNITY center ranking
    applicant_sites = set(
        work_df.loc[work_df["Tags"].fillna("").str.contains(TRAINER_APPLICANT_PAT, case=False, regex=True), "site"]
    )
    p = pairs_df[(~pairs_df["site"].isin(applicant_sites)) & (pairs_df["site"] != "Unknown site")].copy()
    p["trainer_eligible"] = p["post_score"] >= BENCHMARK

    rows = []
    for site, g in p.groupby("site"):
        # aggregate to PERSON first so every figure is per learner, not per assessment
        per_person = g.groupby("name_key").agg(
            eligible=("trainer_eligible", "max"),    # eligible if >=85 on any topic here
            gain=("gain", "mean"),
            pre=("pre_score", "mean"),
            post=("post_score", "mean"),
        )
        if len(per_person) < min_n:
            continue
        rows.append({
            "center": site,
            "learners": int(len(per_person)),
            "mean_gain": round(per_person["gain"].mean(), 1),
            "mean_pretest": round(per_person["pre"].mean(), 1),
            "mean_posttest": round(per_person["post"].mean(), 1),
            "pct_reaching_85": round(100 * per_person["eligible"].mean(), 1),
            "n_trainer_eligible": int(per_person["eligible"].sum()),
        })
    return {
        "min_n_per_center": min_n,
        "by_absolute_outcome": sorted(rows, key=lambda r: -r["pct_reaching_85"]),
        "by_value_added": sorted(rows, key=lambda r: -r["mean_gain"]),
        "caveat": ("Two lenses on purpose: a center serving learners who start lower can show "
                   "the largest gain yet a lower pass rate. Read both before judging a center."),
    }


def trainer_pipeline(work_df, min_n=5):
    """Trainer applicants = records whose Tags flag staff/AmeriCorps/volunteer/pre-employment.
    Qualification on a topic = achieving >= 85% on any attempt of that topic."""
    appl = work_df[work_df["Tags"].fillna("").str.contains(TRAINER_APPLICANT_PAT, case=False, regex=True)].copy()
    if len(appl) == 0:
        return {"available": False, "reason": "no trainer-applicant records detected"}
    appl["qualified"] = appl["Score Percentage"] >= BENCHMARK
    by_topic = []
    for topic, g in appl.groupby("Topic"):
        people = g["name_key"].nunique()
        if people < min_n:
            continue
        qualified_people = g[g["qualified"]]["name_key"].nunique()
        by_topic.append({
            "topic": topic,
            "applicants": int(people),
            "qualified_85": int(qualified_people),
            "pct_qualified": round(100 * qualified_people / people, 1),
        })
    return {
        "available": True,
        "note": "Confirm with the team that these tags identify trainer applicants.",
        "total_applicant_records": int(len(appl)),
        "distinct_applicants": int(appl["name_key"].nunique()),
        "by_topic_qualification": sorted(by_topic, key=lambda r: -r["pct_qualified"]),
        "min_n_per_topic": min_n,
    }
