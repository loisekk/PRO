#!/usr/bin/env python3
"""
Contribution Skyline — isometric 3D contribution graph generator.

Reads a GitHub user's contribution calendar and renders a self-contained,
animated SVG (no third-party hosts, no dependencies beyond the stdlib).

Data source
  - GITHUB_TOKEN set  -> GraphQL API (used inside GitHub Actions)
  - otherwise         -> public contribution calendar page (local preview)

Env
  GH_USER        GitHub username (default: GITHUB_REPOSITORY_OWNER or "loisekk")
  GITHUB_TOKEN   token for the GraphQL API
  SKYLINE_OUT    output path (default: dist/contribution-skyline.svg)
"""
import html
import json
import math
import os
import re
import urllib.request
from datetime import date, datetime, timedelta

USER = os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "loisekk"
TOKEN = os.environ.get("GITHUB_TOKEN")
OUT = os.environ.get("SKYLINE_OUT", "dist/contribution-skyline.svg")


# ───────────────────────────── data ─────────────────────────────
def fetch_graphql():
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }"""
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": {"login": USER}}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
                 "User-Agent": "contribution-skyline"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return {d["date"]: d["contributionCount"] for w in weeks for d in w["contributionDays"]}


def fetch_scrape():
    req = urllib.request.Request(
        f"https://github.com/users/{USER}/contributions",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        page = r.read().decode("utf-8", "replace")
    cells = {}
    for m in re.finditer(r'<td[^>]*?data-date="([\d-]+)"[^>]*?id="([^"]+)"', page):
        cells[m.group(2)] = m.group(1)
    counts = {}
    for m in re.finditer(r'<tool-tip[^>]*?for="([^"]+)"[^>]*>\s*([^<]*)', page):
        cid, text = m.group(1), m.group(2).strip()
        if cid not in cells:
            continue
        n = re.match(r"(\d+)\s+contribution", text)
        counts[cells[cid]] = int(n.group(1)) if n else 0
    return counts


def load():
    data = fetch_graphql() if TOKEN else fetch_scrape()
    if not data:
        raise SystemExit("no contribution data returned")
    return data


# ───────────────────────────── helpers ─────────────────────────────
def hex_to_rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def mix(a, b, p):
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return "#%02x%02x%02x" % tuple(round(ra[i] * (1 - p) + rb[i] * p) for i in range(3))


STOPS = ["#22d3ee", "#818cf8", "#a855f7", "#e879f9"]


def ramp(t):
    t = max(0.0, min(1.0, t))
    pos = t * (len(STOPS) - 1)
    i = min(int(pos), len(STOPS) - 2)
    return mix(STOPS[i], STOPS[i + 1], pos - i)


def stats(days):
    ordered = sorted(days)
    total = sum(days.values())
    active = sum(1 for v in days.values() if v > 0)
    best = max(days.values())
    longest = run = 0
    for d in ordered:
        run = run + 1 if days[d] > 0 else 0
        longest = max(longest, run)
    # current streak: counts back from today (or yesterday if today is empty)
    cur = 0
    d = date.fromisoformat(ordered[-1])
    if days[ordered[-1]] == 0:
        d -= timedelta(days=1)
    while d.isoformat() in days and days[d.isoformat()] > 0:
        cur += 1
        d -= timedelta(days=1)
    return total, active, best, longest, cur


# ───────────────────────────── render ─────────────────────────────
def render(days):
    ordered = sorted(days)
    first = date.fromisoformat(ordered[0])
    # column index: weeks start on Sunday
    def wd(d):          # Sunday = 0
        return (d.weekday() + 1) % 7
    start = first - timedelta(days=wd(first))
    cells = []
    for iso in ordered:
        d = date.fromisoformat(iso)
        w = (d - start).days // 7
        cells.append((w, wd(d), days[iso], d))
    n_weeks = max(c[0] for c in cells) + 1
    max_c = max(c[2] for c in cells) or 1

    total, active, best, longest, current = stats(days)

    # projection (azimuth / elevation)
    phi, eps = math.radians(20), math.radians(33)
    wx, wy = math.cos(phi), math.sin(phi) * math.sin(eps)       # week axis
    dx, dy = -math.sin(phi), math.cos(phi) * math.sin(eps)      # day axis

    W = 1100
    pad = 46
    # fit scale so the grid fits the canvas width
    xs = [gx * wx + gy * dx for gx in (-0.8, n_weeks + 0.8) for gy in (-0.8, 7.8)]
    u = (W - 2 * pad) / (max(xs) - min(xs))
    hmax = 150.0

    def P(gx, gy, z=0.0):
        return (u * (gx * wx + gy * dx), u * (gx * wy + gy * dy) - z)

    def height(c):
        return 0.0 if c == 0 else 7 + (hmax - 7) * (c / max_c) ** 0.6

    g = 0.10  # gap between bars
    # bounding box (for layout)
    pts = [P(-0.8, -0.8), P(n_weeks + 0.8, -0.8), P(n_weeks + 0.8, 7.8), P(-0.8, 7.8)]
    pts += [P(w + 0.5, d + 0.5, height(c)) for w, d, c, _ in cells if c]
    minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
    miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
    header_h = 150
    tx = (W - (maxx - minx)) / 2 - minx
    ty = header_h - miny
    H = int(ty + maxy + 82)

    def T(p):
        return (p[0] + tx, p[1] + ty)

    def pt(gx, gy, z=0.0):
        x, y = T(P(gx, gy, z))
        return f"{x:.1f},{y:.1f}"

    out = []
    defs = [
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b0f1a"/><stop offset="1" stop-color="#05060b"/></linearGradient>',
        '<radialGradient id="glow" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#7c3aed" stop-opacity="0.38"/><stop offset="1" stop-color="#7c3aed" stop-opacity="0"/></radialGradient>',
        '<linearGradient id="legend" x1="0" y1="0" x2="1" y2="0">'
        + "".join(f'<stop offset="{i/3:.2f}" stop-color="{c}"/>' for i, c in enumerate(STOPS)) + "</linearGradient>",
    ]

    out.append(f'<rect width="{W}" height="{H}" rx="22" fill="url(#bg)"/>')
    out.append(f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="21" fill="none" stroke="#1f2937" stroke-width="2"/>')
    out.append(f'<ellipse cx="{W/2:.0f}" cy="{ty + (miny+maxy)/2 + 40:.0f}" rx="{W*0.46:.0f}" ry="{(maxy-miny)*0.62:.0f}" fill="url(#glow)"/>')

    # ── header ──
    out.append('<text x="46" y="52" class="mono" font-size="12" letter-spacing="4" fill="#a78bfa">CONTRIBUTION SKYLINE</text>')
    out.append(f'<text x="46" y="106" class="sans" font-size="48" font-weight="800" fill="#ffffff">{total:,}</text>')
    out.append('<text x="46" y="130" class="sans" font-size="15" fill="#9ca3af">contributions in the last year</text>')
    blocks = [("LONGEST STREAK", f"{longest}d"), ("CURRENT STREAK", f"{current}d"),
              ("ACTIVE DAYS", f"{active}"), ("BEST DAY", f"{best}")]
    bx = W - 46 - 4 * 142
    for i, (label, val) in enumerate(blocks):
        x = bx + i * 142
        out.append(f'<text x="{x}" y="96" class="sans" font-size="30" font-weight="700" fill="{STOPS[i]}">{val}</text>')
        out.append(f'<text x="{x}" y="118" class="mono" font-size="10" letter-spacing="2" fill="#6b7280">{label}</text>')
    out.append(f'<line x1="46" y1="{header_h-8}" x2="{W-46}" y2="{header_h-8}" stroke="#1f2937"/>')

    # ── base plate ──
    t = 12
    a, b, c_, d_ = (-0.8, -0.8), (n_weeks + 0.8, -0.8), (n_weeks + 0.8, 7.8), (-0.8, 7.8)
    def plate(corners, z=0.0):
        return " ".join(pt(x, y, z) for x, y in corners)
    out.append(f'<polygon points="{plate([d_, c_], 0)} {plate([c_, d_], t)}" fill="#0f1422"/>')
    out.append(f'<polygon points="{plate([c_, b], 0)} {plate([b, c_], t)}" fill="#0a0d18"/>')
    out.append(f'<polygon points="{plate([a, b, c_, d_])}" fill="#111827" stroke="#27304a" stroke-width="1.2"/>')

    # month labels along the front edge
    last_label_w = -10
    ang = math.degrees(math.atan2(wy, wx))
    for w, d, cnt, dt in cells:
        if dt.day <= 7 and d == 0 and w - last_label_w >= 3:
            x, y = T(P(w + 0.2, 8.5))
            out.append(f'<text x="{x:.1f}" y="{y:.1f}" class="mono" font-size="11" fill="#6b7280" transform="rotate({ang:.1f} {x:.1f} {y:.1f})">{dt.strftime("%b").upper()}</text>')
            last_label_w = w

    # ── bars (painter's order: far -> near) ──
    order = sorted(cells, key=lambda c: (c[0] * math.sin(phi) + c[1] * math.cos(phi), c[1], c[0]))
    for w, d, cnt, dt in order:
        x0, x1, y0, y1 = w + g, w + 1 - g, d + g, d + 1 - g
        if cnt == 0:
            out.append(f'<polygon points="{pt(x0,y0)} {pt(x1,y0)} {pt(x1,y1)} {pt(x0,y1)}" fill="#171d2b" fill-opacity="0.9"/>')
            continue
        z = height(cnt)
        col = ramp((cnt / max_c) ** 0.6)
        top = f"{pt(x0,y0,z)} {pt(x1,y0,z)} {pt(x1,y1,z)} {pt(x0,y1,z)}"
        front = f"{pt(x0,y1,z)} {pt(x1,y1,z)} {pt(x1,y1)} {pt(x0,y1)}"
        right = f"{pt(x1,y0,z)} {pt(x1,y1,z)} {pt(x1,y1)} {pt(x1,y0)}"
        rd, wv = round(w * 0.03, 2), round(w * 0.07, 2)
        tip = html.escape(f"{cnt} contribution{'s' if cnt != 1 else ''} on {dt.strftime('%b %d, %Y')}")
        out.append(
            f'<g class="b" style="animation-delay:{rd}s,{wv}s">'
            f'<title>{tip}</title>'
            f'<polygon points="{front}" fill="{mix(col, "#000000", 0.42)}"/>'
            f'<polygon points="{right}" fill="{mix(col, "#000000", 0.62)}"/>'
            f'<polygon points="{top}" fill="{mix(col, "#ffffff", 0.12)}"/>'
            f'</g>'
        )

    # ── footer ──
    fy = H - 30
    out.append(f'<text x="46" y="{fy}" class="sans" font-size="13" font-style="italic" fill="#6b7280">Rebuilt daily from the GitHub contribution calendar.</text>')
    out.append(f'<text x="{W-46-210}" y="{fy}" class="mono" font-size="10" letter-spacing="2" fill="#6b7280" text-anchor="end">LESS</text>')
    out.append(f'<rect x="{W-46-200}" y="{fy-10}" width="150" height="9" rx="4" fill="url(#legend)"/>')
    out.append(f'<text x="{W-46}" y="{fy}" class="mono" font-size="10" letter-spacing="2" fill="#6b7280" text-anchor="end">MORE</text>')

    style = """
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}
  .sans{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
  .b{transform-box:fill-box;transform-origin:50% 100%;animation:rise 1.1s cubic-bezier(.2,.8,.2,1) both,wave 5s ease-in-out infinite}
  @keyframes rise{from{transform:scaleY(.02)}to{transform:scaleY(1)}}
  @keyframes wave{0%,100%{opacity:.74}50%{opacity:1}}
  @media (prefers-reduced-motion:reduce){.b{animation:none}}
"""
    label = html.escape(f"Isometric 3D contribution skyline for {USER}: {total} contributions in the last year")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{label}">\n'
        f"<title>{label}</title>\n<style>{style}</style>\n<defs>{''.join(defs)}</defs>\n"
        + "\n".join(out) + "\n</svg>\n"
    )


def main():
    data = load()
    svg = render(data)
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {OUT} ({len(svg)//1024} KB) for {USER}: {sum(data.values())} contributions")


if __name__ == "__main__":
    main()
