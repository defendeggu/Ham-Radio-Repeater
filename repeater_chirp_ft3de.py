#!/usr/bin/env python3
"""
Swiss Repeater CHIRP CSV Generator — Yaesu FT3DE
Fetches Swiss repeaters from RepeaterBook.com and organises them by Grossregion.

Usage:
  python repeater_chirp_ft3de.py                    # fetch live from repeaterbook.com
  python repeater_chirp_ft3de.py switzerland.json   # use a locally saved JSON export

Requirements:
  pip install requests
"""

import sys
import json
import csv
import os
from typing import Optional

try:
    import requests
except ImportError:
    sys.exit("Missing dependency — run:  pip install requests")

# ── Swiss Grossregionen ────────────────────────────────────────────────────────
# Kanton-Kürzel → Grossregion; Kanalblock-Start pro Region
GROSSREGIONEN: dict[str, dict] = {
    "Genferseeregion":  {"cantons": ["GE", "VD", "VS"],              "start": 0},
    "Espace Mittelland":{"cantons": ["BE", "FR", "SO", "NE", "JU"],  "start": 150},
    "Nordwestschweiz":  {"cantons": ["AG", "BL", "BS"],              "start": 300},
    "Zuerich":          {"cantons": ["ZH"],                           "start": 400},
    "Ostschweiz":       {"cantons": ["GL", "SH", "AR", "AI", "SG", "GR", "TG"], "start": 450},
    "Zentralschweiz":   {"cantons": ["LU", "UR", "SZ", "OW", "NW", "ZG"], "start": 650},
    "Tessin":           {"cantons": ["TI"],                           "start": 800},
}

# RepeaterBook speichert Kantone auf Englisch
CANTON_MAP: dict[str, str] = {
    "geneva": "GE", "vaud": "VD", "valais": "VS", "wallis": "VS",
    "bern": "BE", "fribourg": "FR", "freiburg": "FR",
    "solothurn": "SO", "neuchatel": "NE", "neuenburg": "NE", "jura": "JU",
    "aargau": "AG", "argovia": "AG",
    "basel-landschaft": "BL", "baselland": "BL", "basel-stadt": "BS",
    "glarus": "GL", "schaffhausen": "SH",
    "appenzell ausserrhoden": "AR", "appenzell innerrhoden": "AI", "appenzell": "AI",
    "st. gallen": "SG", "st gallen": "SG", "saint-gall": "SG",
    "graubunden": "GR", "graubuenden": "GR", "grisons": "GR",
    "thurgau": "TG",
    "lucerne": "LU", "luzern": "LU",
    "uri": "UR", "schwyz": "SZ", "obwalden": "OW", "nidwalden": "NW", "zug": "ZG",
    "ticino": "TI", "tessin": "TI",
    "zurich": "ZH", "zuerich": "ZH",
}

CHIRP_FIELDS = [
    "Location", "Name", "Frequency", "Duplex", "Offset", "Tone",
    "rToneFreq", "cToneFreq", "DtcsCode", "DtcsPolarity", "Mode",
    "TStep", "Skip", "Comment", "URCALL", "RPT1CALL", "RPT2CALL", "DVCODE",
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def canton_abbr(state: str) -> str:
    return CANTON_MAP.get(state.lower().strip(), "??")

def grossregion(canton: str) -> Optional[str]:
    for name, data in GROSSREGIONEN.items():
        if canton in data["cantons"]:
            return name
    return None

def duplex_offset(out_hz: float, in_hz: float) -> tuple[str, str]:
    if in_hz <= 0 or out_hz == in_hz:
        return "", "0.00000"
    return ("-" if in_hz < out_hz else "+"), f"{abs(out_hz - in_hz):.5f}"

def tone_fields(pl: str) -> tuple[str, str]:
    try:
        val = float(pl or 0)
        if val > 0:
            return "Tone", str(val)
    except ValueError:
        pass
    return "", "88.5"

def chirp_mode(use: str) -> str:
    u = (use or "").upper()
    if "D-STAR" in u or "DSTAR" in u:
        return "DV"
    if "NFM" in u or "NARROW" in u:
        return "NFM"
    return "FM"  # FM, C4FM, DMR → FM (FT3DE AMS handles the rest)

# ── Fetch ──────────────────────────────────────────────────────────────────────

def fetch_repeaterbook() -> list:
    url = "https://www.repeaterbook.com/api/exportROW.php"
    headers = {
        "User-Agent": "CHIRP/Daily (https://chirp.danplanet.com)",
        "Accept":     "application/json",
        "Referer":    "https://www.repeaterbook.com/",
    }
    r = requests.get(url, params={"country": "Switzerland", "format": "json"},
                     headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("results", data) if isinstance(data, dict) else data

# ── Build CHIRP rows ───────────────────────────────────────────────────────────

def build_rows(repeaters: list) -> list:
    by_region: dict[str, list] = {r: [] for r in GROSSREGIONEN}
    skipped = 0

    for rep in repeaters:
        state  = rep.get("State", rep.get("state", ""))
        canton = canton_abbr(state)
        region = grossregion(canton)
        if region:
            by_region[region].append((canton, rep))
        else:
            skipped += 1

    if skipped:
        print(f"  ⚠  {skipped} Repeater ohne Kanton-Zuordnung übersprungen")

    rows = []
    for region_name, rdata in GROSSREGIONEN.items():
        entries = sorted(by_region[region_name],
                         key=lambda x: float(x[1].get("Frequency") or 0))
        loc = rdata["start"]

        for canton, rep in entries:
            out_freq = float(rep.get("Frequency") or 0)
            if out_freq == 0:
                continue

            in_freq = float(rep.get("Input Freq") or rep.get("input_freq") or 0)
            duplex, offset = duplex_offset(out_freq, in_freq)
            tone, rtone   = tone_fields(rep.get("PL") or rep.get("pl") or "")
            mode          = chirp_mode(rep.get("Use") or rep.get("use") or "")
            callsign      = (rep.get("Callsign") or rep.get("callsign") or "")[:8]
            city          = rep.get("Nearest City") or rep.get("nearest_city") or ""

            rows.append({
                "Location":    loc,
                "Name":        callsign,
                "Frequency":   f"{out_freq:.5f}",
                "Duplex":      duplex,
                "Offset":      offset,
                "Tone":        tone,
                "rToneFreq":   rtone,
                "cToneFreq":   "88.5",
                "DtcsCode":    "023",
                "DtcsPolarity":"NN",
                "Mode":        mode,
                "TStep":       "12.5",
                "Skip":        "",
                "Comment":     f"{region_name} | {city} | {canton}",
                "URCALL":      "",
                "RPT1CALL":    "",
                "RPT2CALL":    "",
                "DVCODE":      "",
            })
            loc += 1

    return rows

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Load data
    if len(sys.argv) >= 2 and os.path.isfile(sys.argv[1]):
        print(f"Lade {sys.argv[1]} ...")
        with open(sys.argv[1], encoding="utf-8") as f:
            raw = json.load(f)
        repeaters = raw.get("results", raw.get("repeaters", raw)) if isinstance(raw, dict) else raw
    else:
        print("Lade Schweizer Repeater von repeaterbook.com ...")
        try:
            repeaters = fetch_repeaterbook()
        except Exception as exc:
            print(f"\nFehler: {exc}")
            print(
                "\nAlternative — JSON manuell herunterladen:\n"
                "  1. Bei repeaterbook.com einloggen\n"
                "  2. https://www.repeaterbook.com/api/exportROW.php?country=Switzerland&format=json\n"
                "     im Browser öffnen → Seite als switzerland.json speichern\n"
                f"  3. python {sys.argv[0]} switzerland.json"
            )
            sys.exit(1)

    print(f"  {len(repeaters)} Repeater geladen")

    rows = build_rows(repeaters)

    out = "CH_Repeaters_FT3DE.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CHIRP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{len(rows)} Kanäle geschrieben → {out}")
    print("\nKanalverteilung nach Grossregion:")
    print(f"  {'Region':<25} {'Kanäle':>8}  Block     Kantone")
    print(f"  {'-'*65}")

    region_counts: dict[str, int] = {}
    for row in rows:
        r = row["Comment"].split(" | ")[0]
        region_counts[r] = region_counts.get(r, 0) + 1

    for name, rdata in GROSSREGIONEN.items():
        count  = region_counts.get(name, 0)
        start  = rdata["start"]
        end    = start + count - 1 if count else start
        cants  = ", ".join(rdata["cantons"])
        print(f"  {name:<25} {count:>5} Rep.  {start:>3}–{end:<3}  {cants}")

    print(f"\nImport in CHIRP: File ▸ Import ▸ {out}")

if __name__ == "__main__":
    main()
