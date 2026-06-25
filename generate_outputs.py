#!/usr/bin/env python3
"""
Generate dashboard.html, funder_report_DRAFT.md, and site_staff_report_DRAFT.md
from the current outputs/ folder.

Usage:
    python3 generate_outputs.py [--outdir outputs]
"""
import argparse, json
from pathlib import Path

MIN_N_SITE = 10   # hide sites below this headcount in public-facing reports


def load(outdir):
    d = Path(outdir)
    return (
        json.loads((d / "summary.json").read_text()),
        json.loads((d / "audit.json").read_text()),
        json.loads((d / "weak_points.json").read_text()),
        json.loads((d / "centers.json").read_text()),
    )


# ── dashboard ────────────────────────────────────────────────────────────────

def build_dashboard(summary, audit, weak, centers):
    s = json.dumps(summary)
    a = json.dumps(audit)
    w = json.dumps(weak)
    c = json.dumps(centers)
    merges_note = ""
    if audit.get("confirmed_merges_applied"):
        merges_note = (f"{audit['confirmed_merges_applied']} human-confirmed name merges applied, "
                       f"adding {audit.get('new_pairs_from_merges', 0)} new pairs. ")

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mission: Ignite -- Proof of Learning</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1"></script>
<style>
:root{{--ink:#1b2a4a;--teal:#1aa7a0;--violet:#6b5bd2;--muted:#6b7280;--card:#fff;--bg:#f4f6fa}}
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px}}
header{{background:var(--ink);color:#fff;border-radius:12px;padding:22px 26px;margin-bottom:18px}}
header h1{{margin:0;font-size:21px}}header p{{margin:6px 0 0;opacity:.8;font-size:13px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:18px}}
.card{{background:var(--card);border-radius:12px;padding:18px 20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.kpi .label{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
.kpi .val{{font-size:30px;font-weight:800;margin:4px 0}}.kpi .sub{{font-size:12px;color:var(--muted)}}
.charts{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:18px}}
.charts h3{{font-size:14px;margin:0 0 12px}}canvas{{max-height:300px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:9px 11px;text-align:left;border-bottom:1px solid #eef0f4}}
th{{font-size:11px;text-transform:uppercase;color:var(--muted)}}td.n{{font-weight:700}}
.note{{font-size:12px;color:var(--muted);margin-top:8px}}
@media(max-width:760px){{.charts{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<header><h1>Mission: Ignite &mdash; Proof of Learning</h1>
<p>Every number is backed by a real headcount. Generated from matched pre/post records &bull; benchmark = 85%.</p></header>
<section class="kpis" id="kpis"></section>
<section class="charts">
<div class="card"><h3>Average gain by topic (with N people)</h3><canvas id="gainChart"></canvas></div>
<div class="card"><h3>Gain distribution (all matched learners)</h3><canvas id="distChart"></canvas></div>
</section>
<section class="card"><h3>By topic &mdash; defensible detail</h3>
<table id="topicTable"><thead><tr><th>Topic</th><th>People</th><th>Mean pre</th><th>Mean post</th><th>Mean gain</th><th>% reached 85%</th></tr></thead><tbody></tbody></table>
<p class="note" id="auditNote"></p></section>
<section class="card"><h3>Where to improve &mdash; weakest instruction first</h3>
<table id="weakTable"><thead><tr><th>Topic</th><th>People</th><th>Mean gain</th><th>% still below 85% after training</th></tr></thead><tbody></tbody></table>
<p class="note" id="weakNote"></p></section>
<section class="card"><h3>Center leaderboard &mdash; two honest lenses</h3>
<table id="centerTable"><thead><tr><th>Center</th><th>Learners</th><th>Mean gain (value added)</th><th>% reaching 85% (trainer-eligible)</th></tr></thead><tbody></tbody></table>
<p class="note" id="centerNote"></p></section>
<section class="card"><h3>Trainer pipeline &mdash; applicants clearing the 85% bar</h3>
<table id="trainerTable"><thead><tr><th>Topic</th><th>Applicants</th><th>Qualified (&ge;85%)</th><th>% qualified</th></tr></thead><tbody></tbody></table>
<p class="note" id="trainerNote"></p></section>
</div>
<script>
const SUMMARY={s};
const AUDIT={a};
const WEAK={w};
const CENTERS={c};
const o=SUMMARY.overall;
const kpis=[
 ["Matched learners",AUDIT.distinct_people_with_a_pair.toLocaleString(),AUDIT.matched_pairs.toLocaleString()+" pre/post pairs"],
 ["Mean gain","+"+o.mean_gain+" pts","across "+o.n_people+" people"],
 ["Improved",o.pct_improved+"%",o.n_improved+" people gained"],
 ["Reached 85% benchmark",o.pct_reaching_benchmark_post+"%",o.n_reaching_benchmark_post+" people"]];
document.getElementById('kpis').innerHTML=kpis.map(k=>
 `<div class="card kpi"><div class="label">${{k[0]}}</div><div class="val">${{k[1]}}</div><div class="sub">${{k[2]}}</div></div>`).join('');
const topics=Object.entries(SUMMARY.by_topic).sort((a,b)=>b[1].n_people-a[1].n_people);
new Chart(gainChart,{{type:'bar',data:{{labels:topics.map(t=>t[0]),
 datasets:[{{label:'Mean gain (pts)',data:topics.map(t=>t[1].mean_gain),backgroundColor:'#1aa7a0'}}]}},
 options:{{plugins:{{tooltip:{{callbacks:{{afterLabel:c=>'N = '+topics[c.dataIndex][1].n_people+' people'}}}}}},
 scales:{{y:{{title:{{display:true,text:'points'}}}}}}}}}});
const d=o.gain_distribution;
new Chart(distChart,{{type:'doughnut',data:{{labels:Object.keys(d),
 datasets:[{{data:Object.values(d),backgroundColor:['#e05a5a','#9aa3b2','#1aa7a0','#6b5bd2','#1b2a4a']}}]}}}});
document.querySelector('#topicTable tbody').innerHTML=topics.map(([t,v])=>
 `<tr><td>${{t}}</td><td class="n">${{v.n_people}}</td><td>${{v.mean_pre}}</td><td>${{v.mean_post}}</td><td class="n">+${{v.mean_gain}}</td><td>${{v.pct_reaching_benchmark_post}}%</td></tr>`).join('');
const mergesNote="{merges_note}";
document.getElementById('auditNote').textContent=
 `Honesty footer: built from ${{AUDIT.matched_pairs.toLocaleString()}} pre/post pairs `+
 `(${{AUDIT.distinct_people_with_a_pair}} people). `+mergesNote+
 `Excluded & reported: ${{AUDIT.records_phase_unknown}} records with no phase tag, `+
 `${{AUDIT.ambiguous_cells_resolved_by_rule}} ambiguous cells resolved by rule, `+
 `${{AUDIT.name_review_candidates}} near-duplicate name pair(s) pending review.`;
const weak=(WEAK.topic_level&&WEAK.topic_level.by_outcome_worst_first)||[];
const weakFiltered=weak.filter(r=>r.people>=30);
document.querySelector('#weakTable tbody').innerHTML=weakFiltered.map(r=>
 `<tr><td>${{r.topic}}</td><td class="n">${{r.people}}</td><td>+${{r.mean_gain}}</td><td class="n">${{r.pct_below_benchmark_after_training}}%</td></tr>`).join('');
const skillOn=WEAK.skill_level&&WEAK.skill_level.available;
document.getElementById('weakNote').textContent=skillOn
 ?"Skill-level detail is active from the item-level export."
 :"Topic-level view (n≥30 only). Skill-level (‘which exact questions’) activates automatically if Mission: Ignite exports item-level data.";
const cl=(CENTERS.center_leaderboard&&CENTERS.center_leaderboard.by_absolute_outcome)||[];
document.querySelector('#centerTable tbody').innerHTML=cl.map(r=>
 `<tr><td>${{r.center}}</td><td class="n">${{r.learners}}</td><td>+${{r.mean_gain}}</td><td class="n">${{r.pct_reaching_85}}% (${{r.n_trainer_eligible}})</td></tr>`).join('');
document.getElementById('centerNote').textContent=(CENTERS.center_leaderboard&&CENTERS.center_leaderboard.caveat)||"";
const tp=CENTERS.trainer_pipeline||{{}};
if(tp.available){{
 document.querySelector('#trainerTable tbody').innerHTML=tp.by_topic_qualification.map(r=>
  `<tr><td>${{r.topic}}</td><td class="n">${{r.applicants}}</td><td>${{r.qualified_85}}</td><td class="n">${{r.pct_qualified}}%</td></tr>`).join('');
 document.getElementById('trainerNote').textContent=
  `${{tp.distinct_applicants}} distinct trainer applicants detected. ${{tp.note}}`;
}}else{{
 document.getElementById('trainerNote').textContent="No trainer-applicant records detected.";
}}
</script></body></html>"""


# ── funder report ─────────────────────────────────────────────────────────────

def build_funder_report(summary, audit, weak, centers):
    o = summary["overall"]
    topics_sorted = sorted(
        summary["by_topic"].items(),
        key=lambda x: -x[1]["n_people"]
    )
    # Weak points with n >= 30 (exclude tiny topics)
    weak_rows = [r for r in weak["topic_level"].get("by_outcome_worst_first", [])
                 if r["people"] >= 30][:3]

    match_method = "exact-name"
    if audit.get("confirmed_merges_applied"):
        match_method = (f"exact-name + {audit['confirmed_merges_applied']} "
                        f"human-confirmed name merges")

    topic_table = "\n".join(
        f"| {t} | {v['n_people']} | {v['mean_pre']} | {v['mean_post']} "
        f"| +{v['mean_gain']} | {v['pct_reaching_benchmark_post']}% |"
        for t, v in topics_sorted
    )

    weak_bullets = "\n".join(
        f"- **{r['topic']}**: {r['pct_below_benchmark_after_training']}% of learners "
        f"are still below benchmark after training (n={r['people']}) — "
        f"a priority for curriculum review."
        for r in weak_rows
    )

    merges_line = ""
    if audit.get("confirmed_merges_applied"):
        merges_line = (f" {audit['confirmed_merges_applied']} near-duplicate name pairs "
                       f"confirmed by human review, adding {audit.get('new_pairs_from_merges', 0)} "
                       f"additional pairs.")

    return f"""# Mission: Ignite — Proof of Learning (Funder Report)

## The headline

- **{o['pct_reaching_benchmark_post']}%** of matched learners reached the 85% benchmark after training — that is **{o['n_reaching_benchmark_post']:,} real people**.
- Average skill gain of **+{o['mean_gain']} points** across **{o['n_people']:,} learners**.
- **{o['pct_improved']}%** improved their score ({o['n_improved']:,} people).

## Results by topic (every number carries its headcount)

| Topic | People | Mean pre | Mean post | Mean gain | % reached 85% |
|---|---|---|---|---|---|
{topic_table}

## Where we are focusing improvement

{weak_bullets}

---
_Built from {audit['matched_pairs']:,} pre/post pairs ({audit['distinct_people_with_a_pair']:,} people) using {match_method}.{merges_line} Excluded and reported: {audit['records_phase_unknown']:,} records with no before/after label, {audit['ambiguous_cells_resolved_by_rule']} ambiguous cells resolved by rule, {audit['name_review_candidates']} near-duplicate name pair(s) pending human review._

_No learner names appear in this report._"""


# ── site-staff report ─────────────────────────────────────────────────────────

def build_site_report(summary, audit, weak, centers):
    # All-sites table: use by_site from summary, filter >= MIN_N_SITE people
    by_site = {
        site: v for site, v in summary["by_site"].items()
        if v["n_people"] >= MIN_N_SITE
    }
    sites_sorted = sorted(by_site.items(), key=lambda x: -x[1]["n_people"])
    n_sites = len(sites_sorted)

    site_table = "\n".join(
        f"| {site} | {v['n_people']} | +{v['mean_gain']} | {v['pct_reaching_benchmark_post']}% |"
        for site, v in sites_sorted
    )

    # Center leaderboard (excludes trainer-applicant sites, already filtered)
    cl = centers["center_leaderboard"]["by_absolute_outcome"]
    center_table = "\n".join(
        f"| {r['center']} | {r['learners']} | +{r['mean_gain']} "
        f"| {r['pct_reaching_85']}% ({r['n_trainer_eligible']}) |"
        for r in cl
    )

    # Trainer pipeline
    tp = centers["trainer_pipeline"]
    trainer_section = ""
    if tp.get("available"):
        trainer_rows = "\n".join(
            f"| {r['topic']} | {r['applicants']} | {r['qualified_85']} | {r['pct_qualified']}% |"
            for r in tp["by_topic_qualification"]
        )
        trainer_section = f"""## Trainer pipeline — applicants clearing the 85% qualification bar

_{tp['distinct_applicants']} distinct applicants detected. {tp['note']}_

| Topic | Applicants | Qualified (≥85%) | % qualified |
|---|---|---|---|
{trainer_rows}
"""

    match_method = "exact-name"
    if audit.get("confirmed_merges_applied"):
        match_method = (f"exact-name + {audit['confirmed_merges_applied']} "
                        f"human-confirmed name merges")

    return f"""# How Your Site Is Doing (Site-Staff Report)

_Sites with fewer than {MIN_N_SITE} matched learners are hidden to protect small groups and keep numbers honest._

| Site | People | Mean gain | % reached 85% |
|---|---|---|---|
{site_table}

_{n_sites} sites shown._

## Center leaderboard — who is doing best (two honest lenses)

_Read both columns: a center serving lower-starting learners can show the biggest gain yet a lower pass rate. The 85% column doubles as the trainer-eligibility rate._

| Center | Learners | Mean gain | % reaching 85% (trainer-eligible) |
|---|---|---|---|
{center_table}

{trainer_section}---
_Built from {audit['matched_pairs']:,} pre/post pairs ({audit['distinct_people_with_a_pair']:,} people) using {match_method}. Excluded and reported: {audit['records_phase_unknown']:,} records with no before/after label, {audit['ambiguous_cells_resolved_by_rule']} ambiguous cells resolved by rule, {audit['name_review_candidates']} near-duplicate name pair(s) pending human review._"""


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="outputs")
    a = ap.parse_args()
    outdir = Path(a.outdir)

    summary, audit, weak, centers = load(outdir)

    dashboard = build_dashboard(summary, audit, weak, centers)
    funder    = build_funder_report(summary, audit, weak, centers)
    site      = build_site_report(summary, audit, weak, centers)

    (outdir / "dashboard.html").write_text(dashboard, encoding="utf-8")
    (outdir / "funder_report_DRAFT.md").write_text(funder, encoding="utf-8")
    (outdir / "site_staff_report_DRAFT.md").write_text(site, encoding="utf-8")

    print(f"Written to {outdir}/:")
    print(f"  dashboard.html")
    print(f"  funder_report_DRAFT.md")
    print(f"  site_staff_report_DRAFT.md")
    print(f"\nKey numbers:")
    o = summary["overall"]
    print(f"  {audit['distinct_people_with_a_pair']:,} people  |  "
          f"{audit['matched_pairs']:,} pairs  |  "
          f"+{o['mean_gain']} pts mean gain  |  "
          f"{o['pct_reaching_benchmark_post']}% reached 85%")
    if audit.get("confirmed_merges_applied"):
        print(f"  ({audit['confirmed_merges_applied']} confirmed merges, "
              f"{audit.get('new_pairs_from_merges', 0)} new pairs unlocked)")


if __name__ == "__main__":
    main()
