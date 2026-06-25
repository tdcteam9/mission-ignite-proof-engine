#!/usr/bin/env python3
"""
Mission: Ignite — Proof Engine
Drop a Northstar CSV export → instant, defensible, headcount-backed proof-of-learning.

Features
--------
* Custom proficiency benchmark (slider)
* Date-range filter
* Quarter-over-quarter comparison (optional second CSV)
* Per-site PDF reports (ZIP download)
* One-click Funder Report + Executive Summary PDFs

Deploy:  streamlit run app.py   |   share.streamlit.io (free)
"""
import io, json, re, zipfile
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

try:
    from weasyprint import HTML as WPhtml
    HAVE_PDF = True
except Exception:
    HAVE_PDF = False

# ─── constants ────────────────────────────────────────────────────────────────
DEFAULT_BENCHMARK = 85
PHASE_TOKENS  = {"preassessment", "postassessment", "pre", "post"}
SEASON_RE     = re.compile(r"(spring|summer|fall|autumn|winter)\b", re.I)
YEAR_RE       = re.compile(r"\b(19|20)\d{2}\b")
REVIEWER_RE   = re.compile(r"reviewed", re.I)
TRAINER_PAT   = r"staff|americorps|volunteer|pre-employment|pre employment"
MIN_N_CENTER  = 10
MIN_N_SITE_PDF = 10   # min learners to include site in ZIP

NORTHSTAR_COLS = [
    "Assessment ID", "User Name", "User Email", "Topic", "Software Version",
    "Legacy vs New", "Start", "End", "Duration (h:mm:ss)",
    "Duration (mins)", "Duration (seconds)", "Num Correct", "Num Possible",
    "Score Percentage", "Passed", "Proctored", "Proctor", "Northstar Location", "Tags",
]


# ─── data engine ──────────────────────────────────────────────────────────────

def normalize_name(raw):
    if not isinstance(raw, str): return ""
    s = re.sub(r"[^\w\s'-]", "", raw.strip().lower())
    return re.sub(r"\s+", " ", s)

def parse_phase(tags):
    if not isinstance(tags, str): return "unknown"
    t = tags.lower()
    pre, post = "pre" in t, "post" in t
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

def load_csv(file_bytes):
    raw = pd.read_csv(io.BytesIO(file_bytes), header=None, dtype=str)
    raw.columns = NORTHSTAR_COLS[:len(raw.columns)]
    raw = raw[raw["Score Percentage"] != "Score Percentage"].copy()
    raw["Score Percentage"] = pd.to_numeric(raw["Score Percentage"], errors="coerce")
    raw["Start"] = pd.to_datetime(raw["Start"], errors="coerce", utc=True)
    return raw

def build_work(df):
    w = df.copy()
    w["name_key"] = w["User Name"].map(normalize_name)
    w["phase"]    = w["Tags"].map(parse_phase)
    w["site"]     = w["Tags"].map(parse_site)
    return w

def build_pairs(work):
    """Build matched pre→post pairs. Stores raw scores + pre_date (no benchmark baked in)."""
    usable = work[work["phase"].isin(["pre", "post"])].copy()
    pairs = []
    for (name, topic), grp in usable.groupby(["name_key", "Topic"]):
        pres  = grp[grp.phase == "pre"].sort_values("Start")
        posts = grp[grp.phase == "post"].sort_values("Start")
        if len(pres) == 0 or len(posts) == 0: continue
        pre, post = pres.iloc[0], posts.iloc[-1]
        pairs.append({
            "name_key":   name,
            "topic":      topic,
            "site":       pre["site"] if pre["site"] != "Unknown site" else post["site"],
            "pre_score":  pre["Score Percentage"],
            "post_score": post["Score Percentage"],
            "gain":       round(post["Score Percentage"] - pre["Score Percentage"], 2),
            "pre_date":   pre["Start"],
        })
    return pd.DataFrame(pairs)

def summarize(pairs, benchmark):
    """Compute summary stats. benchmark is passed in — not hardcoded."""
    if len(pairs) == 0: return {}
    p = pairs.copy()
    p["post_passed"] = p["post_score"] >= benchmark
    p["improved"]    = p["gain"] > 0

    def blk(d):
        return {
            "n_pairs":          int(len(d)),
            "n_people":         int(d.name_key.nunique()),
            "mean_pre":         round(d.pre_score.mean(), 1),
            "mean_post":        round(d.post_score.mean(), 1),
            "mean_gain":        round(d.gain.mean(), 1),
            "median_gain":      round(d.gain.median(), 1),
            "pct_reaching_85":  round(100 * d.post_passed.mean(), 1),
            "n_reaching_85":    int(d.post_passed.sum()),
            "n_improved":       int(d.improved.sum()),
            "pct_improved":     round(100 * d.improved.mean(), 1),
        }

    o = blk(p)
    buckets = pd.cut(p.gain, [-1e3, -.01, 9.99, 24.99, 49.99, 1e3],
                     labels=["declined", "0–10", "10–25", "25–50", "50+"])
    o["gain_dist"] = {str(k): int(v) for k, v in buckets.value_counts().sort_index().items()}
    return {
        "overall":  o,
        "by_topic": {t: blk(g) for t, g in p.groupby("topic")},
        "by_site":  {s: blk(g) for s, g in p.groupby("site")},
    }

def compute_weak_points(pairs, benchmark):
    p = pairs.copy()
    p["post_passed"] = p["post_score"] >= benchmark
    rows = []
    for topic, g in p.groupby("topic"):
        if g.name_key.nunique() < 5: continue
        n_below = int((~g.post_passed).sum())
        rows.append({
            "topic":        topic,
            "people":       int(g.name_key.nunique()),
            "mean_gain":    round(g.gain.mean(), 1),
            "mean_post":    round(g.post_score.mean(), 1),
            "pct_below_85": round(100 * n_below / len(g), 1),
        })
    return sorted(rows, key=lambda r: -r["pct_below_85"])

def compute_centers(pairs, trainer_sites, benchmark):
    p = pairs.copy()
    p["eligible"] = p["post_score"] >= benchmark
    p = p[(~p["site"].isin(trainer_sites)) & (p["site"] != "Unknown site")]
    rows = []
    for site, g in p.groupby("site"):
        per = g.groupby("name_key").agg(
            eligible=("eligible", "max"), gain=("gain", "mean"),
            pre=("pre_score", "mean"),   post=("post_score", "mean"))
        if len(per) < MIN_N_CENTER: continue
        rows.append({
            "center":             site,
            "learners":           int(len(per)),
            "mean_gain":          round(per.gain.mean(), 1),
            "mean_pre":           round(per.pre.mean(), 1),
            "mean_post":          round(per.post.mean(), 1),
            "pct_reaching_85":    round(100 * per.eligible.mean(), 1),
            "n_trainer_eligible": int(per.eligible.sum()),
        })
    return sorted(rows, key=lambda r: -r["pct_reaching_85"])


@st.cache_data(show_spinner="Loading data…")
def load_and_pair(csv_bytes):
    """Heavy step: parse CSV + build pairs. Cached per file."""
    df    = load_csv(csv_bytes)
    work  = build_work(df)
    pairs = build_pairs(work)
    # Identify trainer-applicant sites once; no need to cache the full work df
    trainer_sites = frozenset(
        work.loc[work["Tags"].fillna("").str.contains(TRAINER_PAT, case=False, regex=True), "site"]
    )
    base_audit = {
        "total_records":     int(len(df)),
        "unknown_phase":     int((work.phase == "unknown").sum()),
        "distinct_learners": int(work.name_key.nunique()),
    }
    return pairs, trainer_sites, base_audit


def filter_pairs(pairs, date_start=None, date_end=None):
    """Apply date-range filter to pairs."""
    p = pairs.copy()
    if date_start is not None:
        p = p[p["pre_date"].dt.date >= date_start]
    if date_end is not None:
        p = p[p["pre_date"].dt.date <= date_end]
    return p


def run_stats(pairs, trainer_sites, benchmark, base_audit):
    """Fast stats pass — not cached so benchmark/date changes recompute instantly."""
    sm    = summarize(pairs, benchmark)
    wp    = compute_weak_points(pairs, benchmark)
    cl    = compute_centers(pairs, trainer_sites, benchmark)
    audit = {
        **base_audit,
        "matched_pairs":   int(len(pairs)),
        "distinct_people": int(pairs.name_key.nunique()) if len(pairs) else 0,
    }
    return sm, wp, cl, audit


# ─── PDF builders ─────────────────────────────────────────────────────────────

def _pill(pct, benchmark):
    mid = benchmark - 10
    if pct >= benchmark:    return f'<span class="pill green">{pct}%</span>'
    if pct >= mid:          return f'<span class="pill yellow">{pct}%</span>'
    return f'<span class="pill red">{pct}%</span>'

PDF_BASE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; color: #1C1C2E; font-size: 13px; line-height: 1.5; }
.page { max-width: 860px; margin: 0 auto; padding: 32px 36px; }
h2.sec { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;
         color: #1A3A5C; border-left: 3px solid #E85D26; padding-left: 7px; margin: 18px 0 10px; }
table { width: 100%; border-collapse: collapse; font-size: 11.5px; margin-bottom: 6px; }
thead tr { background: #1A3A5C; color: #fff; }
thead th { padding: 7px 9px; text-align: left; font-size: 10px; font-weight: 600; }
th.r, td.r { text-align: right; }
tbody tr { border-bottom: 1px solid #DDE2EA; }
tbody tr:nth-child(even) { background: #F7F8FA; }
td { padding: 7px 9px; }
.pill { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 10px; font-weight: 700; }
.pill.green  { background: #D4EDDA; color: #1A7A4A; }
.pill.yellow { background: #FFF3CD; color: #856404; }
.pill.red    { background: #FADBD8; color: #C0392B; }
footer { border-top: 1px solid #DDE2EA; padding-top: 10px; margin-top: 18px;
         font-size: 9.5px; color: #5A6275; line-height: 1.5; }
.no-names { display: inline-block; margin-top: 5px; background: #F7F8FA;
            border: 1px solid #DDE2EA; border-radius: 3px; padding: 2px 8px;
            font-size: 9px; font-weight: 700; color: #1A7A4A; }
"""

FUNDER_EXTRA = """
.header { display: flex; justify-content: space-between; align-items: flex-start;
          border-bottom: 3px solid #E85D26; padding-bottom: 16px; margin-bottom: 22px; }
h1 { font-size: 20px; font-weight: 800; color: #1A3A5C; }
.accent { color: #E85D26; }
.meta { font-size: 11px; color: #5A6275; margin-top: 3px; }
.badge { background: #1A3A5C; color: #fff; padding: 4px 12px; border-radius: 20px;
         font-size: 10px; font-weight: 700; letter-spacing: .5px; white-space: nowrap; }
.hero { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 22px; }
.stat { background: #F7F8FA; border: 1px solid #DDE2EA; border-top: 3px solid #E85D26;
        border-radius: 5px; padding: 14px 16px; text-align: center; }
.big { font-size: 32px; font-weight: 800; color: #1A3A5C; line-height: 1; }
.stat-label { font-size: 11px; color: #5A6275; margin-top: 5px; }
.people { display: inline-block; margin-top: 6px; background: #E85D26; color: #fff;
          font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 10px; }
.imp-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 22px; }
.imp-card { border: 1px solid #F5B7B1; background: #FEF9F9; border-left: 4px solid #C0392B;
            border-radius: 4px; padding: 11px 12px; }
.imp-card .topic { font-weight: 700; font-size: 11.5px; color: #1A3A5C; margin-bottom: 4px; }
.imp-card .pct { font-size: 20px; font-weight: 800; color: #C0392B; line-height: 1; }
.imp-card .sub { font-size: 10px; color: #5A6275; margin-top: 2px; }
.imp-card .action { margin-top: 7px; font-size: 10px; border-top: 1px solid #F5B7B1; padding-top: 6px; }
"""


def build_funder_pdf_html(sm, audit, wp, benchmark, period=""):
    o = sm["overall"]
    topics = sorted(sm["by_topic"].items(), key=lambda x: -x[1]["n_people"])
    top_weak = [r for r in wp if r["people"] >= 30][:3]
    period_str = f" &nbsp;·&nbsp; {period}" if period else ""

    topic_rows = "".join(
        f"""<tr>
          <td><strong>{t}</strong>{"&nbsp;<em style='color:#999;font-size:10px'>(small cohort)</em>" if v["n_people"]<10 else ""}</td>
          <td class="r">{v["n_people"]}</td>
          <td class="r">{v["mean_pre"]}</td>
          <td class="r">{v["mean_post"]}</td>
          <td class="r" style="color:#1A7A4A;font-weight:700">+{v["mean_gain"]}</td>
          <td class="r">{_pill(v["pct_reaching_85"], benchmark)}</td>
        </tr>"""
        for t, v in topics
    )
    weak_cards = "".join(
        f"""<div class="imp-card">
          <div class="topic">{r["topic"]}</div>
          <div class="pct">{r["pct_below_85"]}%</div>
          <div class="sub">of {r["people"]} learners still below {benchmark}% after training</div>
          <div class="action">Priority: curriculum review</div>
        </div>"""
        for r in top_weak
    ) or f"<p style='color:#5A6275;font-size:11px'>No topics with ≥30 learners flagged below {benchmark}%.</p>"

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<style>{PDF_BASE}{FUNDER_EXTRA}</style></head><body><div class="page">
  <div class="header">
    <div>
      <h1>Mission: <span class="accent">Ignite</span> — Proof of Learning</h1>
      <p class="meta">Digital Literacy Program &nbsp;·&nbsp; Funder Impact Report{period_str}</p>
    </div>
    <div class="badge">FUNDER REPORT</div>
  </div>
  <div class="hero">
    <div class="stat">
      <div class="big">{o["pct_improved"]}%</div>
      <div class="stat-label">of learners improved after training</div>
      <div class="people">{o["n_improved"]:,} real people</div>
    </div>
    <div class="stat">
      <div class="big">+{o["mean_gain"]}</div>
      <div class="stat-label">avg. skill-score gain (0–100 scale)</div>
      <div class="people">{o["n_people"]:,} learners measured</div>
    </div>
    <div class="stat">
      <div class="big">{o["pct_reaching_85"]}%</div>
      <div class="stat-label">reached the {benchmark}% proficiency benchmark</div>
      <div class="people">{o["n_reaching_85"]:,} people at benchmark</div>
    </div>
  </div>
  <h2 class="sec">Results by Topic — every number carries its headcount</h2>
  <table>
    <thead><tr>
      <th>Topic</th><th class="r">Learners</th><th class="r">Pre</th>
      <th class="r">Post</th><th class="r">Avg. Gain</th><th class="r">Reached {benchmark}%</th>
    </tr></thead>
    <tbody>{topic_rows}</tbody>
  </table>
  <h2 class="sec">Where We Are Focusing Improvement</h2>
  <div class="imp-cards">{weak_cards}</div>
  <footer>
    <strong>Data integrity note:</strong> Built from {audit["matched_pairs"]:,} pre/post pairs
    ({audit["distinct_people"]:,} people). Excluded and reported: {audit["unknown_phase"]:,} records with no phase tag.
    <br><span class="no-names">✓ No learner names appear in this report</span>
  </footer>
</div></body></html>"""


def build_exec_pdf_html(sm, audit, wp, cl, benchmark, period=""):
    o = sm["overall"]
    topics = sorted(sm["by_topic"].items(), key=lambda x: -x[1]["n_people"])
    period_str = f" — {period}" if period else ""

    topic_rows = "".join(
        f"""<tr>
          <td><strong>{t}</strong></td>
          <td class="r">{v["n_people"]}</td>
          <td class="r">{v["mean_pre"]}</td>
          <td class="r">{v["mean_post"]}</td>
          <td class="r" style="color:#1A7A4A;font-weight:700">+{v["mean_gain"]}</td>
          <td class="r">{v["pct_reaching_85"]}%</td>
        </tr>"""
        for t, v in topics
    )
    weak_rows = "".join(
        f"""<tr>
          <td><strong>{r["topic"]}</strong></td>
          <td class="r">{r["people"]}</td>
          <td class="r">+{r["mean_gain"]}</td>
          <td class="r">{r["mean_post"]}</td>
          <td class="r" style="color:{'#C0392B' if r['pct_below_85']>=60 else '#856404' if r['pct_below_85']>=45 else '#1A7A4A'};font-weight:700">{r["pct_below_85"]}%</td>
        </tr>"""
        for r in wp if r["people"] >= 10
    )
    center_rows = "".join(
        f"""<tr>
          <td>{r["center"]}</td><td class="r">{r["learners"]}</td>
          <td class="r">+{r["mean_gain"]}</td><td class="r">{r["mean_pre"]}</td>
          <td class="r">{r["mean_post"]}</td><td class="r">{r["pct_reaching_85"]}%</td>
        </tr>"""
        for r in cl[:20]
    )
    dist_rows = "".join(
        f'<tr><td>{k}</td><td class="r" style="font-weight:700">{v:,}</td></tr>'
        for k, v in o.get("gain_dist", {}).items()
    )

    exec_extra = """
    h1 { font-size: 18px; font-weight: 800; color: #1A3A5C;
         border-bottom: 3px solid #E85D26; padding-bottom: 14px; margin-bottom: 20px; }
    .accent { color: #E85D26; }
    .tag { display: inline-block; background: #1A3A5C; color: #fff; padding: 3px 10px;
           border-radius: 20px; font-size: 9px; font-weight: 700; letter-spacing: .5px;
           margin-left: 8px; vertical-align: middle; }
    .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }
    .kpi { background: #F7F8FA; border: 1px solid #DDE2EA; border-radius: 5px;
           padding: 12px 14px; text-align: center; }
    .kpi .big { font-size: 26px; font-weight: 800; color: #1A3A5C; line-height: 1; }
    .kpi .lbl { font-size: 10px; color: #5A6275; margin-top: 4px; }
    .kpi .sub { font-size: 9px; color: #E85D26; font-weight: 700; margin-top: 3px; }
    """

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<style>{PDF_BASE}{exec_extra}</style></head><body><div class="page">
  <h1>Mission: <span class="accent">Ignite</span> — Executive Summary<span class="tag">INTERNAL</span></h1>
  <div class="kpis">
    <div class="kpi"><div class="big">{audit["distinct_people"]:,}</div><div class="lbl">Matched Learners</div><div class="sub">{audit["matched_pairs"]:,} pairs</div></div>
    <div class="kpi"><div class="big">+{o["mean_gain"]}</div><div class="lbl">Mean Skill Gain</div><div class="sub">median +{o["median_gain"]} pts</div></div>
    <div class="kpi"><div class="big">{o["pct_improved"]}%</div><div class="lbl">Improved</div><div class="sub">{o["n_improved"]:,} learners</div></div>
    <div class="kpi"><div class="big">{o["pct_reaching_85"]}%</div><div class="lbl">Reached {benchmark}%</div><div class="sub">{o["n_reaching_85"]:,} people</div></div>
  </div>
  <h2 class="sec">Results by Topic</h2>
  <table>
    <thead><tr><th>Topic</th><th class="r">People</th><th class="r">Pre</th><th class="r">Post</th><th class="r">Gain</th><th class="r">% at {benchmark}%</th></tr></thead>
    <tbody>{topic_rows}</tbody>
  </table>
  <h2 class="sec">Improvement Priorities</h2>
  <table>
    <thead><tr><th>Topic</th><th class="r">People</th><th class="r">Mean Gain</th><th class="r">Mean Post</th><th class="r">% Still Below {benchmark}%</th></tr></thead>
    <tbody>{weak_rows}</tbody>
  </table>
  <h2 class="sec">Center Leaderboard (≥{MIN_N_CENTER} learners)</h2>
  <table>
    <thead><tr><th>Center</th><th class="r">Learners</th><th class="r">Mean Gain</th><th class="r">Mean Pre</th><th class="r">Mean Post</th><th class="r">% at {benchmark}%</th></tr></thead>
    <tbody>{center_rows}</tbody>
  </table>
  <h2 class="sec">Gain Distribution</h2>
  <table style="max-width:260px">
    <thead><tr><th>Range</th><th class="r">Learners</th></tr></thead>
    <tbody>{dist_rows}</tbody>
  </table>
  <footer>
    Built from {audit["matched_pairs"]:,} pre/post pairs ({audit["distinct_people"]:,} people).
    Excluded & reported: {audit["unknown_phase"]:,} records with no phase tag.
    Total records: {audit["total_records"]:,}. Benchmark: {benchmark}%.
    <br><strong>No learner names appear in this report.</strong>
  </footer>
</div></body></html>"""


def build_site_pdf_html(site_name, pairs, network_o, benchmark, period=""):
    """One-page snapshot for a single site, including comparison to network average."""
    site_pairs = pairs[pairs["site"] == site_name].copy()
    if len(site_pairs) == 0:
        return None

    site_sm = summarize(site_pairs, benchmark)
    if not site_sm:
        return None

    o     = site_sm["overall"]
    n_ppl = o["n_people"]
    topics = sorted(site_sm["by_topic"].items(), key=lambda x: -x[1]["n_people"])
    period_str = f" &nbsp;·&nbsp; {period}" if period else ""

    def delta_str(val, net_val):
        d = round(val - net_val, 1)
        if d > 0:  return f'<span style="color:#1A7A4A;font-size:9px">▲ +{d} vs network</span>'
        if d < 0:  return f'<span style="color:#C0392B;font-size:9px">▼ {d} vs network</span>'
        return '<span style="color:#5A6275;font-size:9px">= network avg</span>'

    topic_rows = "".join(
        f"""<tr>
          <td><strong>{t}</strong></td>
          <td class="r">{v["n_people"]}</td>
          <td class="r">{v["mean_pre"]}</td>
          <td class="r">{v["mean_post"]}</td>
          <td class="r" style="color:#1A7A4A;font-weight:700">+{v["mean_gain"]}</td>
          <td class="r">{_pill(v["pct_reaching_85"], benchmark)}</td>
        </tr>"""
        for t, v in topics
    )

    site_extra = """
    .header { border-bottom: 3px solid #E85D26; padding-bottom: 14px; margin-bottom: 20px; }
    h1 { font-size: 18px; font-weight: 800; color: #1A3A5C; }
    .site-name { font-size: 13px; color: #5A6275; margin-top: 3px; }
    .accent { color: #E85D26; }
    .badge { display: inline-block; background: #1A3A5C; color: #fff; padding: 4px 12px;
             border-radius: 20px; font-size: 10px; font-weight: 700; float: right; }
    .hero { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 22px; }
    .stat { background: #F7F8FA; border: 1px solid #DDE2EA; border-top: 3px solid #E85D26;
            border-radius: 5px; padding: 14px 16px; text-align: center; }
    .big { font-size: 30px; font-weight: 800; color: #1A3A5C; line-height: 1; }
    .stat-label { font-size: 11px; color: #5A6275; margin-top: 4px; }
    .net-cmp { margin-top: 5px; font-size: 9px; }
    """

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<style>{PDF_BASE}{site_extra}</style></head><body><div class="page">
  <div class="header">
    <span class="badge">SITE REPORT</span>
    <h1>Mission: <span class="accent">Ignite</span></h1>
    <p class="site-name"><strong>{site_name}</strong> &nbsp;·&nbsp; Digital Literacy Program{period_str} &nbsp;·&nbsp; {n_ppl} matched learners</p>
  </div>
  <div class="hero">
    <div class="stat">
      <div class="big">{o["pct_improved"]}%</div>
      <div class="stat-label">improved after training</div>
      <div class="net-cmp">{delta_str(o["pct_improved"], network_o["pct_improved"])}</div>
    </div>
    <div class="stat">
      <div class="big">+{o["mean_gain"]}</div>
      <div class="stat-label">avg. skill-score gain</div>
      <div class="net-cmp">{delta_str(o["mean_gain"], network_o["mean_gain"])}</div>
    </div>
    <div class="stat">
      <div class="big">{o["pct_reaching_85"]}%</div>
      <div class="stat-label">reached {benchmark}% benchmark</div>
      <div class="net-cmp">{delta_str(o["pct_reaching_85"], network_o["pct_reaching_85"])}</div>
    </div>
  </div>
  <h2 class="sec">Results by Topic</h2>
  <table>
    <thead><tr>
      <th>Topic</th><th class="r">Learners</th><th class="r">Pre</th>
      <th class="r">Post</th><th class="r">Gain</th><th class="r">Reached {benchmark}%</th>
    </tr></thead>
    <tbody>{topic_rows}</tbody>
  </table>
  <footer>
    Built from {o["n_pairs"]:,} pre/post pairs at this site ({n_ppl} people). Benchmark: {benchmark}%.
    Network average: +{network_o["mean_gain"]} pts gain &nbsp;·&nbsp; {network_o["pct_reaching_85"]}% at benchmark.
    <br><span class="no-names">✓ No learner names appear in this report</span>
  </footer>
</div></body></html>"""


def render_pdf(html_str):
    if not HAVE_PDF or not html_str:
        return None
    try:
        return WPhtml(string=html_str).write_pdf()
    except Exception:
        return None


def build_site_zip(pairs, sm, benchmark, period=""):
    """Generate a ZIP of per-site PDF reports for all sites with enough learners."""
    network_o = sm["overall"]
    sites_by_size = sorted(
        [(s, v["n_people"]) for s, v in sm["by_site"].items() if v["n_people"] >= MIN_N_SITE_PDF],
        key=lambda x: -x[1]
    )
    if not sites_by_size:
        return None, 0

    zip_buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for site_name, _ in sites_by_size:
            html = build_site_pdf_html(site_name, pairs, network_o, benchmark, period)
            pdf  = render_pdf(html)
            if pdf:
                safe = re.sub(r"[^\w\s-]", "", site_name).strip().replace(" ", "_")
                zf.writestr(f"{safe}.pdf", pdf)
                count += 1

    zip_buf.seek(0)
    return zip_buf.getvalue(), count


# ─── UI sections ──────────────────────────────────────────────────────────────

def section_overview(sm, audit, benchmark, prev_sm=None, prev_audit=None):
    o = sm["overall"]

    # ── Q-o-Q delta calculations ──────────────────────────────────────────────
    def _delta(key, fmt=None, invert=False):
        """Return formatted delta string vs previous period, or None."""
        if prev_sm is None: return None
        po = prev_sm.get("overall", {})
        if key not in po or key not in o: return None
        d = round(o[key] - po[key], 1)
        if invert: d = -d
        if fmt == "pct": return f"{d:+.1f}pp vs prev"
        if fmt == "pts": return f"{d:+.1f} pts vs prev"
        if fmt == "count":
            d_raw = o[key] - po[key]
            return f"{d_raw:+,} vs prev"
        return f"{d:+} vs prev"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("People matched",        f"{audit['distinct_people']:,}",
              _delta("n_people", "count") or f"{audit['matched_pairs']:,} pairs")
    c2.metric("Mean gain",             f"+{o['mean_gain']} pts",
              _delta("mean_gain", "pts") or f"median +{o['median_gain']} pts")
    c3.metric("Improved",              f"{o['pct_improved']}%",
              _delta("pct_improved", "pct") or f"{o['n_improved']:,} learners")
    c4.metric(f"Reached {benchmark}%", f"{o['pct_reaching_85']}%",
              _delta("pct_reaching_85", "pct") or f"{o['n_reaching_85']:,} people")

    if prev_sm:
        st.info(
            f"↑↓ Deltas shown vs previous period "
            f"({prev_audit['distinct_people']:,} people, "
            f"+{prev_sm['overall']['mean_gain']} pts avg gain)",
            icon="📊"
        )

    col_a, col_b = st.columns(2)
    with col_a:
        topics = sorted(sm["by_topic"].items(), key=lambda x: -x[1]["n_people"])
        fig = px.bar(
            x=[t for t, _ in topics],
            y=[v["mean_gain"] for _, v in topics],
            labels={"x": "Topic", "y": "Mean gain (pts)"},
            title="Mean gain by topic",
            color_discrete_sequence=["#1aa7a0"],
            text=[f"n={v['n_people']}" for _, v in topics],
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, margin=dict(t=40, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        dist = o["gain_dist"]
        fig2 = go.Figure(go.Pie(
            labels=list(dist.keys()), values=list(dist.values()),
            marker_colors=["#e05a5a", "#9aa3b2", "#1aa7a0", "#6b5bd2", "#1b2a4a"],
            hole=0.35,
        ))
        fig2.update_layout(title="Gain distribution", margin=dict(t=40, b=0))
        st.plotly_chart(fig2, use_container_width=True)

    st.caption(
        f"Built from {audit['matched_pairs']:,} pre→post pairs "
        f"({audit['distinct_people']:,} people). "
        f"Excluded & reported: {audit['unknown_phase']:,} records with no phase tag. "
        f"Benchmark: {benchmark}%."
    )


def section_topics(sm, benchmark):
    topics = sorted(sm["by_topic"].items(), key=lambda x: -x[1]["n_people"])
    st.dataframe(pd.DataFrame([{
        "Topic":         t,
        "People":        v["n_people"],
        "Mean pre":      v["mean_pre"],
        "Mean post":     v["mean_post"],
        "Mean gain":     f"+{v['mean_gain']}",
        f"% reached {benchmark}%": f"{v['pct_reaching_85']}%",
        f"N reached {benchmark}%": v["n_reaching_85"],
    } for t, v in topics]), use_container_width=True, hide_index=True)


def section_centers(cl, sm, benchmark):
    st.subheader("Center leaderboard")
    st.caption(
        f"Centers with ≥{MIN_N_CENTER} matched learners. "
        "A center serving lower-starting learners may show the biggest gain but a lower pass rate."
    )
    st.dataframe(pd.DataFrame([{
        "Center":         r["center"],
        "Learners":       r["learners"],
        "Mean gain":      f"+{r['mean_gain']}",
        "Mean pre":       r["mean_pre"],
        "Mean post":      r["mean_post"],
        f"% reaching {benchmark}%": f"{r['pct_reaching_85']}%",
        "Trainer-eligible": r["n_trainer_eligible"],
    } for r in cl]), use_container_width=True, hide_index=True)

    st.subheader("All sites")
    by_site = sm.get("by_site", {})
    site_rows = [{
        "Site":    s,
        "People":  v["n_people"],
        "Mean gain": f"+{v['mean_gain']}",
        f"% reached {benchmark}%": f"{v['pct_reaching_85']}%",
    } for s, v in sorted(by_site.items(), key=lambda x: -x[1]["n_people"])
      if v["n_people"] >= MIN_N_CENTER]
    st.dataframe(pd.DataFrame(site_rows), use_container_width=True, hide_index=True)


def section_weak(wp, benchmark):
    st.caption(f"Topics where the most learners are still below {benchmark}% after training.")
    if not wp:
        st.info("No topics with enough data to report.")
        return
    df = pd.DataFrame([{
        "Topic":             r["topic"],
        "People":            r["people"],
        "Mean gain":         r["mean_gain"],
        "Mean post":         r["mean_post"],
        f"% still below {benchmark}%": r["pct_below_85"],
    } for r in wp])
    fig = px.bar(
        df, x="Topic", y=f"% still below {benchmark}%",
        color=f"% still below {benchmark}%", color_continuous_scale="RdYlGn_r",
        text=f"% still below {benchmark}%",
        title=f"% still below {benchmark}% after training (worst first)",
    )
    fig.update_traces(texttemplate="%{text}%", textposition="outside")
    fig.update_layout(coloraxis_showscale=False, margin=dict(t=40, b=0))
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df, use_container_width=True, hide_index=True)


def section_reports(pairs, sm, audit, wp, cl, benchmark, period):
    st.markdown("### Generate Reports")

    # ── PDF report buttons ────────────────────────────────────────────────────
    if not HAVE_PDF:
        st.warning(
            "⚠️ PDF generation requires **weasyprint**. "
            "Add `weasyprint` to `requirements.txt` and "
            "`libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2` to `packages.txt`, "
            "then redeploy.",
            icon="⚠️"
        )

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**📄 Funder Report**")
        st.caption(f"One-pager with headline stats, topic results, and improvement focus. Benchmark: {benchmark}%.")
        if HAVE_PDF:
            pdf = render_pdf(build_funder_pdf_html(sm, audit, wp, benchmark, period))
            if pdf:
                st.download_button("⬇️ Download Funder Report PDF", data=pdf,
                                   file_name="Mission_Ignite_Funder_Report.pdf",
                                   mime="application/pdf", type="primary", use_container_width=True)

    with col2:
        st.markdown("**📋 Executive Summary**")
        st.caption("Full internal detail: all topics, center leaderboard, gain distribution.")
        if HAVE_PDF:
            pdf2 = render_pdf(build_exec_pdf_html(sm, audit, wp, cl, benchmark, period))
            if pdf2:
                st.download_button("⬇️ Download Executive Summary PDF", data=pdf2,
                                   file_name="Mission_Ignite_Executive_Summary.pdf",
                                   mime="application/pdf", type="primary", use_container_width=True)

    st.divider()

    # ── Per-site ZIP ──────────────────────────────────────────────────────────
    st.markdown("### 📦 All Site Reports (ZIP)")
    eligible_sites = [s for s, v in sm.get("by_site", {}).items() if v["n_people"] >= MIN_N_SITE_PDF]
    st.caption(
        f"{len(eligible_sites)} sites qualify (≥{MIN_N_SITE_PDF} learners). "
        "Each PDF shows that site's stats with a comparison to the network average."
    )
    if HAVE_PDF and eligible_sites:
        if st.button("⚙️ Generate all site PDFs", use_container_width=True):
            with st.spinner(f"Generating {len(eligible_sites)} site reports…"):
                zip_bytes, count = build_site_zip(pairs, sm, benchmark, period)
            if zip_bytes and count:
                st.download_button(
                    f"⬇️ Download {count} site reports (ZIP)",
                    data=zip_bytes,
                    file_name="Mission_Ignite_Site_Reports.zip",
                    mime="application/zip",
                    type="primary",
                    use_container_width=True,
                )
    elif not HAVE_PDF:
        pass  # warning already shown above
    else:
        st.info("No sites have enough learners for individual reports yet.")

    st.divider()

    # ── raw data downloads ────────────────────────────────────────────────────
    st.markdown("### Raw Data Downloads")
    from generate_outputs import build_dashboard

    summary_compat = {
        "overall": {**sm["overall"], "gain_distribution": sm["overall"].get("gain_dist", {})},
        "by_topic": {t: {**v, "pct_reaching_benchmark_post": v["pct_reaching_85"],
                         "n_reaching_benchmark_post": v["n_reaching_85"]}
                     for t, v in sm["by_topic"].items()},
        "by_site":  {s: {**v, "pct_reaching_benchmark_post": v["pct_reaching_85"],
                         "n_reaching_benchmark_post": v["n_reaching_85"]}
                     for s, v in sm.get("by_site", {}).items()},
    }
    audit_compat = {
        **audit,
        "matched_pairs":               audit["matched_pairs"],
        "distinct_people_with_a_pair": audit["distinct_people"],
        "records_phase_unknown":       audit["unknown_phase"],
        "ambiguous_cells_resolved_by_rule": 0,
        "name_review_candidates": 0,
        "confirmed_merges_applied": 0,
        "new_pairs_from_merges": 0,
    }
    weak_compat = {
        "topic_level": {
            "by_outcome_worst_first": [{
                "topic": r["topic"], "people": r["people"],
                "mean_gain": r["mean_gain"],
                "pct_below_benchmark_after_training": r["pct_below_85"],
            } for r in wp],
            "min_n_per_topic": 5,
        },
        "skill_level": {"available": False, "reason": "no items file supplied"},
    }
    centers_compat = {
        "center_leaderboard": {
            "min_n_per_center": MIN_N_CENTER,
            "by_absolute_outcome": cl,
            "by_value_added": sorted(cl, key=lambda r: -r["mean_gain"]),
            "caveat": "Two lenses: gain vs. pass rate. Read both before judging a center.",
        },
        "trainer_pipeline": {"available": False},
    }

    ca, cb, cc = st.columns(3)
    try:
        dash = build_dashboard(summary_compat, audit_compat, weak_compat, centers_compat)
        ca.download_button("⬇️ Dashboard HTML", dash.encode(),
                           "dashboard.html", "text/html", use_container_width=True)
    except Exception as e:
        ca.warning(f"Dashboard error: {e}")

    buf = io.BytesIO()
    pairs.to_csv(buf, index=False)
    cb.download_button("⬇️ Matched Pairs CSV", buf.getvalue(),
                       "matched_pairs.csv", "text/csv", use_container_width=True)
    cc.download_button("⬇️ Audit JSON", json.dumps(audit_compat, indent=2).encode(),
                       "audit.json", "application/json", use_container_width=True)


# ─── main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Mission: Ignite — Proof Engine",
        page_icon="🎯",
        layout="wide",
    )

    st.title("🎯 Mission: Ignite — Proof of Learning")
    st.caption(
        "Drop a Northstar Digital Literacy Assessment export to generate "
        "defensible, headcount-backed proof-of-learning numbers."
    )

    # ── sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Upload data")
        csv_file  = st.file_uploader("Current period CSV", type=["csv"],
                                     help="Raw Northstar export. No header row needed.")
        prev_file = st.file_uploader("Previous period CSV (optional)",
                                     type=["csv"],
                                     help="Upload last quarter's export to see quarter-over-quarter deltas.")
        st.divider()

        # Filters — only show after a file is loaded
        benchmark   = DEFAULT_BENCHMARK
        date_range  = None
        has_filters = False

        if csv_file:
            with st.expander("⚙️ Filters & settings", expanded=False):
                benchmark = st.slider(
                    "Proficiency benchmark (%)", 50, 95, DEFAULT_BENCHMARK, step=5,
                    help="The score a learner must reach to 'pass'. Northstar default is 85%."
                )
                st.caption(f"Currently set to **{benchmark}%**. Changing this updates all numbers instantly.")

                # Date range (needs pairs to know min/max)
                # We'll populate this after loading pairs below
                has_filters = True

        period = st.text_input("Report period label",
                               placeholder="e.g. Q3 2025",
                               help="Appears in PDF report headers.")

        st.divider()
        st.markdown(
            "**How it works**\n\n"
            "1. Upload your Northstar CSV\n"
            "2. Adjust benchmark or date range if needed\n"
            "3. Go to **Reports** to download PDFs\n\n"
            "No learner names appear in any report."
        )

    # ── no file ───────────────────────────────────────────────────────────────
    if not csv_file:
        st.info("👈 Upload a Northstar CSV export to get started.", icon="📂")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("People matched", "—")
        c2.metric("Mean gain", "—")
        c3.metric("Improved", "—")
        c4.metric(f"Reached {benchmark}%", "—")
        return

    # ── load current period ───────────────────────────────────────────────────
    try:
        pairs, trainer_sites, base_audit = load_and_pair(csv_file.read())
    except Exception as e:
        st.error(f"Error loading file: {e}")
        st.stop()

    if len(pairs) == 0:
        st.warning("No matched pre→post pairs found. Check that your CSV has both "
                   "pre- and post-assessment records with recognisable phase tags.")
        st.stop()

    # ── date range filter (now we have pairs, so we know min/max) ────────────
    valid_dates = pairs["pre_date"].dropna()
    date_start, date_end = None, None

    if has_filters and len(valid_dates) > 0:
        min_date = valid_dates.dt.date.min()
        max_date = valid_dates.dt.date.max()
        with st.sidebar:
            with st.expander("⚙️ Filters & settings", expanded=False):
                pass  # already rendered benchmark above; date goes in same expander via session state trick

        # Render date filter directly in sidebar (outside the expander to avoid duplicate key)
        with st.sidebar:
            dr = st.date_input(
                "Date range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                help="Filter to assessments that started within this window.",
                key="date_range_filter",
            )
            if isinstance(dr, (list, tuple)) and len(dr) == 2:
                date_start, date_end = dr[0], dr[1]

    # Apply date filter
    pairs_filtered = filter_pairs(pairs, date_start, date_end)
    if len(pairs_filtered) == 0:
        st.warning("No pairs found in the selected date range. Try widening the filter.")
        st.stop()

    # ── compute stats ─────────────────────────────────────────────────────────
    sm, wp, cl, audit = run_stats(pairs_filtered, trainer_sites, benchmark, base_audit)

    # ── load previous period (optional) ───────────────────────────────────────
    prev_sm, prev_audit = None, None
    if prev_file:
        try:
            prev_pairs, prev_trainer, prev_base = load_and_pair(prev_file.read())
            prev_sm, _, _, prev_audit = run_stats(prev_pairs, prev_trainer, benchmark, prev_base)
        except Exception:
            st.sidebar.warning("Could not process previous period file.")

    # ── success banner ────────────────────────────────────────────────────────
    n_sites = len([s for s, v in sm.get("by_site", {}).items() if v["n_people"] >= 1])
    st.success(
        f"✓ **{audit['distinct_people']:,} people matched** across "
        f"**{n_sites} sites** — "
        f"+{sm['overall']['mean_gain']} pts mean gain, "
        f"{sm['overall']['pct_reaching_85']}% reached {benchmark}%",
        icon=None,
    )

    # ── tabs ──────────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "📊 Overview",
        "📚 By Topic",
        "🏫 Centers & Sites",
        "⚠️ Improvement Focus",
        "📥 Reports",
    ])
    with tabs[0]: section_overview(sm, audit, benchmark, prev_sm, prev_audit)
    with tabs[1]: section_topics(sm, benchmark)
    with tabs[2]: section_centers(cl, sm, benchmark)
    with tabs[3]: section_weak(wp, benchmark)
    with tabs[4]: section_reports(pairs_filtered, sm, audit, wp, cl, benchmark, period)


if __name__ == "__main__":
    main()
