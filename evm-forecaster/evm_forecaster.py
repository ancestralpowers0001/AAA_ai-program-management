"""EVM Forecaster: turns monthly PV/EV/AC data into cost and schedule forecasts
plus a plain-English summary a program leader can act on.

Standard library only, so it runs anywhere Python 3.9+ is installed.

Usage:
    python evm_forecaster.py data/sample_program.csv
    python evm_forecaster.py data/sample_program.csv --status-period 6 --out report.md --svg chart.svg
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Period:
    period: int
    pv: float
    ev: float | None
    ac: float | None
    milestone: str = ""


def load_csv(path: str | Path) -> list[Period]:
    """Read a CSV with columns period, pv, ev, ac and an optional milestone.

    Values are cumulative. Future periods carry PV only (the baseline), with
    EV and AC left blank. A milestone names the gate planned to finish in that
    period (PDR, CDR, FAT and so on).
    """
    periods = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            periods.append(
                Period(
                    period=int(row["period"]),
                    pv=float(row["pv"]),
                    ev=float(row["ev"]) if row.get("ev") else None,
                    ac=float(row["ac"]) if row.get("ac") else None,
                    milestone=(row.get("milestone") or "").strip(),
                )
            )
    periods.sort(key=lambda p: p.period)
    if not periods:
        raise ValueError("CSV has no rows")
    return periods


def earned_schedule(pv_curve: list[float], ev: float) -> float:
    """Earned Schedule (ES): the point in time when the current EV was planned.

    ES = C + (EV - PV_C) / (PV_C+1 - PV_C), where C is the number of whole
    periods whose cumulative PV is at or below EV.
    """
    c = sum(1 for pv in pv_curve if pv <= ev)
    if c >= len(pv_curve):
        return float(len(pv_curve))
    pv_c = pv_curve[c - 1] if c > 0 else 0.0
    pv_next = pv_curve[c]
    if pv_next == pv_c:
        return float(c)
    return c + (ev - pv_c) / (pv_next - pv_c)


def _div(a: float, b: float) -> float | None:
    return a / b if b else None


def compute(periods: list[Period], bac: float | None = None, status_period: int | None = None) -> dict:
    """Compute EVM status, trends and forecasts at the status period."""
    actuals = [p for p in periods if p.ev is not None and p.ac is not None]
    if not actuals:
        raise ValueError("No periods with both EV and AC reported")
    if status_period is None:
        status = actuals[-1]
    else:
        matches = [p for p in actuals if p.period == status_period]
        if not matches:
            raise ValueError(f"Status period {status_period} has no EV/AC data")
        status = matches[0]

    bac = bac if bac is not None else periods[-1].pv
    pv_curve = [p.pv for p in periods]
    planned_duration = len(periods)
    at = status.period  # actual time elapsed, in periods

    pv, ev, ac = status.pv, status.ev, status.ac
    cpi = _div(ev, ac)
    spi = _div(ev, pv)

    es = earned_schedule(pv_curve, ev)
    spi_t = _div(es, at)
    ieac_t = _div(planned_duration, spi_t) if spi_t else None

    eac = {
        "remaining at budget rate": ac + (bac - ev),
        "current CPI continues": _div(bac, cpi) if cpi else None,
        "CPI x SPI pressure": ac + _div(bac - ev, cpi * spi) if cpi and spi else None,
    }
    eac_values = [v for v in eac.values() if v is not None]

    tcpi_bac = _div(bac - ev, bac - ac)

    # Remaining gates: forecast = actual time + planned time still ahead / SPI(t).
    # At the final period this equals the overall Earned Schedule forecast.
    milestones = []
    for p in periods:
        if p.milestone and p.period > es and spi_t:
            forecast = at + (p.period - es) / spi_t
            milestones.append({"name": p.milestone, "planned": p.period, "forecast": forecast, "slip": forecast - p.period})
    trend = [
        {"period": p.period, "cpi": _div(p.ev, p.ac), "spi": _div(p.ev, p.pv)}
        for p in actuals
        if p.period <= status.period
    ]

    return {
        "status_period": status.period,
        "planned_duration": planned_duration,
        "bac": bac,
        "pv": pv,
        "ev": ev,
        "ac": ac,
        "percent_complete": _div(ev, bac),
        "cv": ev - ac,
        "sv": ev - pv,
        "cpi": cpi,
        "spi": spi,
        "es": es,
        "spi_t": spi_t,
        "ieac_t": ieac_t,
        "eac": eac,
        "eac_low": min(eac_values),
        "eac_high": max(eac_values),
        "tcpi_bac": tcpi_bac,
        "trend": trend,
        "milestones": milestones,
    }


def tcpi_verdict(cpi: float, tcpi: float | None) -> str:
    """Rule of thumb used in program controls: a TCPI more than about 0.10
    above the CPI to date is rarely achieved in practice."""
    if tcpi is None:
        return "not meaningful (budget already spent)"
    gap = tcpi - cpi
    if gap <= 0.05:
        return "achievable"
    if gap <= 0.10:
        return "aggressive"
    return "not credible"


def summarize(r: dict, units: str = "$K") -> list[str]:
    """Plain-English summary. Conclusion first, then why, then the ask."""
    cpi, spi_t, bac = r["cpi"], r["spi_t"], r["bac"]
    late = r["ieac_t"] - r["planned_duration"] if r["ieac_t"] else 0.0
    over_low = (r["eac_low"] - bac) / bac * 100
    over_high = (r["eac_high"] - bac) / bac * 100
    verdict = tcpi_verdict(cpi, r["tcpi_bac"])

    cost_word = "over budget" if cpi < 1 else "on or under budget"
    sched_word = "behind schedule" if spi_t < 1 else "on or ahead of schedule"

    lines = [
        f"**Bottom line:** the program is {cost_word} and {sched_word}. "
        f"At current performance it finishes {over_low:+.0f}% to {over_high:+.0f}% against budget "
        f"and about {late:.1f} periods {'late' if late > 0 else 'early'}.",
        f"**Why:** every dollar spent is earning {cpi:.2f} dollars of planned work (CPI), "
        f"and the team is progressing at {spi_t:.2f} of planned speed (SPI(t), Earned Schedule).",
    ]
    if r["tcpi_bac"] is not None:
        lines.append(
            f"**Recovery check:** finishing on the original budget needs a TCPI of {r['tcpi_bac']:.2f} "
            f"against a CPI to date of {cpi:.2f}. That is {verdict}."
        )
    if verdict == "not credible":
        lines.append(
            "**Ask:** stop reporting to the original budget. Approve a revised EAC in the range above "
            "and decide now whether to recover scope, schedule, or funding."
        )
    elif verdict == "aggressive":
        lines.append(
            "**Ask:** back the recovery plan with specific actions and owners, and review it again next period."
        )
    else:
        lines.append("**Ask:** none. Hold the current plan and keep watching the trend.")
    if r["percent_complete"] and r["percent_complete"] >= 0.2:
        lines.append(
            f"_Note: the program is {r['percent_complete']:.0%} complete. Past about 20%, cumulative CPI "
            "historically moves very little, so treat it as a reliable signal, not noise._"
        )
    return lines


def _fmt(v: float | None, spec: str = ",.0f") -> str:
    return "n/a" if v is None else format(v, spec)


def render_markdown(r: dict, units: str = "$K", title: str = "EVM Status Report") -> str:
    out = [f"# {title}", "", f"Status at period {r['status_period']} of {r['planned_duration']} (values in {units})", ""]
    for line in summarize(r, units):
        out += [line, ""]
    out += [
        "## Status",
        "",
        "| Metric | Value | Meaning |",
        "|---|---|---|",
        f"| BAC | {_fmt(r['bac'])} | Total budget |",
        f"| PV / EV / AC | {_fmt(r['pv'])} / {_fmt(r['ev'])} / {_fmt(r['ac'])} | Planned, earned, actual to date |",
        f"| % complete | {_fmt(r['percent_complete'], '.0%')} | EV / BAC |",
        f"| CV | {_fmt(r['cv'])} | Negative means over cost |",
        f"| SV | {_fmt(r['sv'])} | Negative means behind (in money terms) |",
        f"| CPI | {_fmt(r['cpi'], '.2f')} | Value earned per unit spent |",
        f"| SPI | {_fmt(r['spi'], '.2f')} | Classic SPI, drifts to 1.00 near the end |",
        f"| SPI(t) | {_fmt(r['spi_t'], '.2f')} | Earned Schedule SPI, stays honest to the end |",
        f"| Earned Schedule | {_fmt(r['es'], '.2f')} periods | Where the program actually is in time |",
        f"| Forecast duration | {_fmt(r['ieac_t'], '.1f')} periods | Planned {r['planned_duration']} |",
        f"| TCPI (to BAC) | {_fmt(r['tcpi_bac'], '.2f')} | Efficiency needed to finish on budget |",
        "",
        "## Cost forecast (EAC)",
        "",
        "| Method | EAC | VAC | Use it when |",
        "|---|---|---|---|",
    ]
    when = {
        "remaining at budget rate": "Past overruns were one-offs and will not repeat",
        "current CPI continues": "Cost performance to date is typical of what is left",
        "CPI x SPI pressure": "There is pressure to recover the schedule, which usually costs more",
    }
    for name, value in r["eac"].items():
        vac = r["bac"] - value if value is not None else None
        out.append(f"| {name} | {_fmt(value)} | {_fmt(vac)} | {when[name]} |")
    if r["milestones"]:
        out += [
            "",
            "## Upcoming gates (Earned Schedule forecast)",
            "",
            "| Gate | Planned period | Forecast period | Slip |",
            "|---|---|---|---|",
        ]
        for m in r["milestones"]:
            out.append(f"| {m['name']} | {m['planned']} | {m['forecast']:.1f} | {m['slip']:+.1f} |")
    out += ["", "## Trend", "", "| Period | CPI | SPI |", "|---|---|---|"]
    for t in r["trend"]:
        out.append(f"| {t['period']} | {_fmt(t['cpi'], '.2f')} | {_fmt(t['spi'], '.2f')} |")
    out.append("")
    return "\n".join(out)


def render_svg(periods: list[Period], r: dict, width: int = 720, height: int = 400) -> str:
    """S-curve chart: PV baseline, EV and AC to date, and the EAC forecast."""
    pad_l, pad_r, pad_t, pad_b = 64, 150, 40, 48
    n = max(len(periods), math.ceil(r["ieac_t"] or 0))
    top = max(r["eac_high"], r["bac"]) * 1.08
    magnitude = 10 ** math.floor(math.log10(top / 5))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= top / 5)
    ticks = math.ceil(top / step)
    y_max = step * ticks
    pw, ph = width - pad_l - pad_r, height - pad_t - pad_b

    def x(t: float) -> float:
        return pad_l + t / n * pw

    def y(v: float) -> float:
        return pad_t + ph - v / y_max * ph

    def path(points: list[tuple[float, float]]) -> str:
        return " ".join(f"{'M' if i == 0 else 'L'}{x(t):.1f},{y(v):.1f}" for i, (t, v) in enumerate(points))

    done = [p for p in periods if p.ev is not None and p.period <= r["status_period"]]
    pv_pts = [(0, 0)] + [(p.period, p.pv) for p in periods]
    ev_pts = [(0, 0)] + [(p.period, p.ev) for p in done]
    ac_pts = [(0, 0)] + [(p.period, p.ac) for p in done]
    fc_end = (r["ieac_t"] or len(periods), r["eac"]["current CPI continues"] or r["eac_high"])
    fc_pts = [(r["status_period"], r["ac"]), fc_end]

    s = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="12">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{pad_l}" y="24" font-size="15" font-weight="bold" fill="#1f2937">'
        f'EVM S-curve, status at period {r["status_period"]}</text>',
    ]
    for i in range(ticks + 1):
        v = step * i
        s.append(f'<line x1="{pad_l}" x2="{pad_l + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e5e7eb"/>')
        s.append(f'<text x="{pad_l - 8}" y="{y(v) + 4:.1f}" text-anchor="end" fill="#6b7280">{v:,.0f}</text>')
    for t in range(0, n + 1, max(1, n // 6)):
        s.append(f'<text x="{x(t):.1f}" y="{pad_t + ph + 18}" text-anchor="middle" fill="#6b7280">{t}</text>')
    s.append(f'<text x="{pad_l + pw / 2}" y="{height - 10}" text-anchor="middle" fill="#6b7280">Period</text>')
    s.append(f'<line x1="{pad_l}" x2="{pad_l + pw}" y1="{y(r["bac"]):.1f}" y2="{y(r["bac"]):.1f}" stroke="#9ca3af" stroke-dasharray="2 3"/>')

    series = [
        ("PV (baseline)", pv_pts, "#2563eb", ""),
        ("EV (earned)", ev_pts, "#16a34a", ""),
        ("AC (actual)", ac_pts, "#dc2626", ""),
        ("EAC forecast", fc_pts, "#dc2626", ' stroke-dasharray="6 4"'),
    ]
    for i, (label, pts, color, dash) in enumerate(series):
        s.append(f'<path d="{path(pts)}" fill="none" stroke="{color}" stroke-width="2.5"{dash}/>')
        ly = pad_t + 16 + i * 20
        s.append(f'<line x1="{pad_l + pw + 16}" x2="{pad_l + pw + 40}" y1="{ly}" y2="{ly}" stroke="{color}" stroke-width="2.5"{dash}/>')
        s.append(f'<text x="{pad_l + pw + 46}" y="{ly + 4}" fill="#1f2937">{label}</text>')
    s.append(f'<text x="{pad_l + pw + 16}" y="{pad_t + 110}" fill="#6b7280">dotted line = BAC</text>')
    for p in periods:
        if p.milestone:
            s.append(f'<circle cx="{x(p.period):.1f}" cy="{y(p.pv):.1f}" r="3.5" fill="#ffffff" stroke="#2563eb" stroke-width="2"/>')
            s.append(f'<text x="{x(p.period) - 6:.1f}" y="{y(p.pv) - 8:.1f}" text-anchor="end" font-size="10" fill="#2563eb">{p.milestone}</text>')
    plan_end = len(periods)
    s.append(f'<line x1="{x(plan_end):.1f}" x2="{x(plan_end):.1f}" y1="{pad_t}" y2="{pad_t + ph}" stroke="#9ca3af" stroke-dasharray="2 3"/>')
    s.append(f'<text x="{x(plan_end) - 4:.1f}" y="{pad_t + 12}" text-anchor="end" fill="#6b7280">planned finish</text>')
    s.append(f'<circle cx="{x(fc_end[0]):.1f}" cy="{y(fc_end[1]):.1f}" r="4" fill="#dc2626"/>')
    s.append(f'<text x="{x(fc_end[0]) - 6:.1f}" y="{y(fc_end[1]) - 10:.1f}" text-anchor="end" fill="#dc2626" font-weight="bold">'
             f'EAC {fc_end[1]:,.0f} at period {fc_end[0]:.1f}</text>')
    s.append("</svg>")
    return "\n".join(s)


def main() -> None:
    ap = argparse.ArgumentParser(description="EVM cost and schedule forecaster")
    ap.add_argument("csv", help="CSV with cumulative period, pv, ev, ac")
    ap.add_argument("--bac", type=float, help="Budget at completion (defaults to final PV)")
    ap.add_argument("--status-period", type=int, help="Period to report on (defaults to latest)")
    ap.add_argument("--units", default="$K", help="Label for money values")
    ap.add_argument("--out", help="Write the markdown report to this file")
    ap.add_argument("--svg", help="Write an S-curve chart to this SVG file")
    args = ap.parse_args()

    periods = load_csv(args.csv)
    result = compute(periods, bac=args.bac, status_period=args.status_period)
    report = render_markdown(result, units=args.units)

    if args.out:
        Path(args.out).write_text(report)
    else:
        print(report)
    if args.svg:
        Path(args.svg).write_text(render_svg(periods, result))


if __name__ == "__main__":
    main()
