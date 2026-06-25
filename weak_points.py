#!/usr/bin/env python3
"""
Weak-point analysis
===================
topic_weak_points  -- which topics still have the most learners below the 85% bar
                       after training, surfaced as an actionable ranked list.
item_weak_points   -- question/skill-level analysis; requires an item-level data file
                       that is not in the standard Northstar export (stub, ready when data arrives).
"""
import pandas as pd

BENCHMARK = 85.0


def topic_weak_points(pairs_df):
    """Rank topics by % of learners still below benchmark after training (worst first)."""
    if len(pairs_df) == 0:
        return {"note": "no matched pairs"}

    rows = []
    for topic, g in pairs_df.groupby("topic"):
        n_pairs = len(g)
        n_people = int(g["name_key"].nunique())
        n_below = int((g["post_score"] < BENCHMARK).sum())
        rows.append({
            "topic": topic,
            "people": n_people,
            "n_pairs": n_pairs,
            "n_still_below_benchmark": n_below,
            "pct_below_benchmark_after_training": round(100 * n_below / n_pairs, 1),
            "mean_gain": round(g["gain"].mean(), 1),
            "mean_post": round(g["post_score"].mean(), 1),
        })

    rows_sorted = sorted(rows, key=lambda r: -r["pct_below_benchmark_after_training"])
    return {
        "benchmark": BENCHMARK,
        "by_outcome_worst_first": rows_sorted,
        "note": (
            "Topics where the highest share of learners are still below the 85% benchmark "
            "after training — prioritize for curriculum or coaching attention."
        ),
    }


def item_weak_points(items_path, work_df):
    """Skill/item-level weak points require a question-level data file.
    The standard Northstar export is topic-level only; this activates when that
    file is supplied via --items."""
    try:
        items = pd.read_csv(items_path)
        # Placeholder: join on learner + topic, count per-item failure rates.
        # Full implementation depends on the item-level file schema.
        return {
            "available": False,
            "reason": "item-level file loaded but analysis not yet implemented — share schema",
            "item_file_shape": list(items.shape),
            "item_file_columns": list(items.columns),
        }
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
