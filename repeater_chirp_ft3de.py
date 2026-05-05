#!/usr/bin/env python3
"""
Swiss + Neighbouring Repeater CHIRP CSV Generator — Yaesu FT3DE
Fetches Swiss repeaters from RepeaterBook.com, organises them by Grossregion,
and appends repeaters from DE/FR/IT/AT/LI within 50 km of the Swiss border,
grouped by country.

Usage:
  python repeater_chirp_ft3de.py                   # live fetch (uses Chrome session if available)
  python repeater_chirp_ft3de.py data/             # read pre-downloaded JSON files from a folder
                                                   # (files must be named e.g. Switzerland.json,
                                                   #  Germany.json, France.json, ...)

Requirements:
  pip install requests
  pip install browser-cookie3    # optional — uses your logged-in Chrome session automatically
"""

import sys, json, csv, os, math, time
from typing import Optional

try:
    import requests
except ImportError:
    sys.exit("Missing dependency — run:  pip install requests")

try:
    import browser_cookie3
    _BC3 = True
except ImportError:
    _BC3 = False

# ── Swiss Grossregionen ────────────────────────────────────────────────────────
GROSSREGIONEN: dict[str, dict] = {
    "Genferseeregion":   {"cantons": ["GE", "VD", "VS"],                          "start": 0},
    "Espace Mittelland": {"cantons": ["BE", "FR", "SO", "NE", "JU"],              "start": 100},
    "Nordwestschweiz":   {"cantons": ["AG", "BL", "BS"],                          "start": 200},
    "Zuerich":           {"cantons": ["ZH"],                                       "start": 270},
    "Ostschweiz":        {"cantons": ["GL", "SH", "AR", "AI", "SG", "GR", "TG"], "start": 320},
    "Zentralschweiz":    {"cantons": ["LU", "UR", "SZ", "OW", "NW", "ZG"],       "start": 500},
    "Tessin":            {"cantons": ["TI"],                                       "start": 580},
}

# Neighbouring countries — each gets a channel block after Switzerland
# (start is filled in dynamically after Swiss channels are counted)
NEIGHBOUR_COUNTRIES: list[str] = ["France", "Germany", "Austria", "Italy", "Liechtenstein"]

COUNTRY_LABEL: dict[str, str] = {
    "France":        "Frankreich",
    "Germany":       "Deutschland",
    "Austria":       "Oesterreich",
    "Italy":         "Italien",
    "Liechtenstein": "Liechtenstein",
}

# ── Canton name → abbreviation (RepeaterBook uses English names) ───────────────
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

# ── Reference points along the Swiss border (lat, lon) ────────────────────────
# Used to calculate minimum distance of a foreign repeater to Switzerland.
# ~30 points spread around the perimeter give a good approximation.
SWISS_BORDER: list[tuple[float, float]] = [
    (46.204, 6.143),   # Geneva
    (46.375, 6.230),   # Nyon area
    (46.515, 6.500),   # Morges
    (46.520, 6.632),   # Lausanne
    (46.460, 6.840),   # Vevey
    (46.435, 6.920),   # Montreux
    (46.254, 6.943),   # Monthey
    (46.101, 7.074),   # Martigny
    (46.233, 7.360),   # Sion
    (46.293, 7.535),   # Sierre
    (46.319, 7.987),   # Brig
    (46.250, 8.035),   # Simplon pass area
    (46.169, 8.799),   # Locarno
    (46.194, 9.020),   # Bellinzona
    (46.005, 8.948),   # Lugano
    (45.833, 9.023),   # Chiasso
    (46.380, 10.060),  # Poschiavo area
    (46.803, 9.838),   # Davos
    (46.850, 9.530),   # Chur
    (47.168, 9.470),   # Vaduz area / Buchs
    (47.420, 9.655),   # St. Margrethen
    (47.550, 9.770),   # Kreuzlingen east
    (47.650, 9.175),   # Kreuzlingen
    (47.697, 8.637),   # Schaffhausen
    (47.620, 8.220),   # Waldshut area
    (47.560, 7.589),   # Basel
    (47.560, 7.200),   # Laufenburg area
    (47.600, 6.850),   # Belfort gap / Porrentruy
    (46.800, 6.360),   # Pontarlier area
]

BORDER_MAX_KM = 50.0    # include foreign repeaters within this distance

# Bounding box with generous buffer — quick pre-filter before Haversine
BB_LAT = (45.25, 48.35)
BB_LON = (5.30, 11.20)

CHIRP_FIELDS = [
    "Location", "Name", "Frequency", "Duplex", "Offset", "Tone",
    "rToneFreq", "cToneFreq", "DtcsCode", "DtcsPolarity", "Mode",
    "TStep", "Skip", "Comment", "URCALL", "RPT1CALL", "RPT2CALL", "DVCODE",
]

# ── Geometry ───────────────────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))

def min_dist_to_ch(lat: float, lon: float) -> float:
    """Minimum distance (km) from a point to the Swiss border reference points."""
    return min(haversine(lat, lon, blat, blon) for blat, blon in SWISS_BORDER)

def in_bounding_box(lat: float, lon: float) -> bool:
    return BB_LAT[0] <= lat <= BB_LAT[1] and BB_LON[0] <= lon <= BB_LON[1]

# ── Repeater field helpers ─────────────────────────────────────────────────────

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
    return "FM"  # FM and C4FM both work as FM on FT3DE (AMS handles it)

def rep_coords(rep: dict) -> tuple[float, float]:
    try:
        lat = float(rep.get("Lat") or rep.get("lat") or 0)
        lon = float(rep.get("Long") or rep.get("long") or rep.get("Lon") or rep.get("lon") or 0)
        return lat, lon
    except (ValueError, TypeError):
        return 0.0, 0.0

def make_row(loc: int, rep: dict, label: str) -> dict:
    out_freq = float(rep.get("Frequency") or 0)
    in_freq  = float(rep.get("Input Freq") or rep.get("input_freq") or 0)
    duplex, offset = duplex_offset(out_freq, in_freq)
    tone, rtone    = tone_fields(rep.get("PL") or rep.get("pl") or "")
    mode           = chirp_mode(rep.get("Use") or rep.get("use") or "")
    callsign       = (rep.get("Callsign") or rep.get("callsign") or "")[:8]
    city           = rep.get("Nearest City") or rep.get("nearest_city") or ""
    return {
        "Location":     loc,
        "Name":         callsign,
        "Frequency":    f"{out_freq:.5f}",
        "Duplex":       duplex,
        "Offset":       offset,
        "Tone":         tone,
        "rToneFreq":    rtone,
        "cToneFreq":    "88.5",
        "DtcsCode":     "023",
        "DtcsPolarity": "NN",
        "Mode":         mode,
        "TStep":        "12.5",
        "Skip":         "",
        "Comment":      f"{label} | {city}",
        "URCALL":       "",
        "RPT1CALL":     "",
        "RPT2CALL":     "",
        "DVCODE":       "",
    }

# ── Network fetch ──────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "CHIRP/Daily (https://chirp.danplanet.com)",
        "Accept":     "application/json",
        "Referer":    "https://www.repeaterbook.com/",
    })
    if _BC3:
        try:
            cookies = browser_cookie3.chrome(domain_name=".repeaterbook.com")
            s.cookies.update(cookies)
            print("  [browser-cookie3] Chrome-Session geladen")
        except Exception as e:
            print(f"  [browser-cookie3] Cookie-Fehler (ignoriert): {e}")
    return s

def fetch_country(country: str, session: requests.Session) -> list:
    url = "https://www.repeaterbook.com/api/exportROW.php"
    r = session.get(url, params={"country": country, "format": "json"}, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data.get("results", data.get("repeaters", data)) if isinstance(data, dict) else data

# ── Load data (live or from folder) ───────────────────────────────────────────

def load_all(data_dir: Optional[str]) -> dict[str, list]:
    """Returns dict: country_name → list of repeater dicts."""
    all_countries = ["Switzerland"] + NEIGHBOUR_COUNTRIES
    result: dict[str, list] = {}

    if data_dir:
        # Load from pre-downloaded JSON files in a folder
        for country in all_countries:
            candidates = [
                os.path.join(data_dir, f"{country}.json"),
                os.path.join(data_dir, f"{country.lower()}.json"),
            ]
            for path in candidates:
                if os.path.isfile(path):
                    with open(path, encoding="utf-8") as f:
                        raw = json.load(f)
                    reps = raw.get("results", raw.get("repeaters", raw)) if isinstance(raw, dict) else raw
                    result[country] = reps
                    print(f"  {country:<15}: {len(reps):>4} Repeater aus {os.path.basename(path)}")
                    break
            else:
                print(f"  {country:<15}: keine Datei gefunden (übersprungen)")
    else:
        # Live fetch
        session = _session()
        for country in all_countries:
            print(f"  Lade {country} ...", end=" ", flush=True)
            try:
                reps = fetch_country(country, session)
                result[country] = reps
                print(f"{len(reps)} Repeater")
            except Exception as exc:
                print(f"FEHLER: {exc}")
                result[country] = []
            time.sleep(1.2)   # be polite to the server

    return result

# ── Build CHIRP rows ───────────────────────────────────────────────────────────

def build_swiss_rows(repeaters: list) -> tuple[list, int]:
    """Returns (rows, next_free_location)."""
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
        print(f"  Schweiz: {skipped} Repeater ohne Kanton-Zuordnung übersprungen")

    rows = []
    next_loc = 0

    for region_name, rdata in GROSSREGIONEN.items():
        entries = sorted(by_region[region_name],
                         key=lambda x: float(x[1].get("Frequency") or 0))
        loc = rdata["start"]
        # Sanity: never collide with previous region
        loc = max(loc, next_loc)

        for canton, rep in entries:
            out_freq = float(rep.get("Frequency") or 0)
            if out_freq == 0:
                continue
            rows.append(make_row(loc, rep, f"{region_name} | {canton}"))
            loc += 1

        next_loc = loc

    return rows, next_loc


def build_neighbour_rows(country_data: dict[str, list], start_loc: int) -> list:
    """Filter by proximity and build rows grouped by country."""
    rows = []
    loc = start_loc

    for country in NEIGHBOUR_COUNTRIES:
        repeaters = country_data.get(country, [])
        label     = COUNTRY_LABEL[country]

        # Filter: in bounding box AND within BORDER_MAX_KM of CH border
        nearby = []
        for rep in repeaters:
            lat, lon = rep_coords(rep)
            if lat == 0 and lon == 0:
                continue
            if not in_bounding_box(lat, lon):
                continue
            dist = min_dist_to_ch(lat, lon)
            if dist <= BORDER_MAX_KM:
                nearby.append((dist, rep))

        # Sort by frequency within each country
        nearby.sort(key=lambda x: float(x[1].get("Frequency") or 0))

        print(f"  {country:<15}: {len(nearby):>4} Repeater innerhalb {BORDER_MAX_KM:.0f} km "
              f"(von {len(repeaters)} gesamt)")

        for dist, rep in nearby:
            out_freq = float(rep.get("Frequency") or 0)
            if out_freq == 0:
                continue
            state = rep.get("State") or rep.get("state") or ""
            rows.append(make_row(loc, rep, f"{label} | {state}"))
            rows[-1]["Comment"] += f" | {dist:.0f} km"
            loc += 1

    return rows

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    data_dir = None
    if len(sys.argv) >= 2:
        if os.path.isdir(sys.argv[1]):
            data_dir = sys.argv[1]
        else:
            sys.exit(f"Argument '{sys.argv[1]}' ist weder ein Verzeichnis noch gültig.\n"
                     f"Usage: python {sys.argv[0]} [data_folder/]")

    if not data_dir and not _BC3:
        print("Tipp: 'pip install browser-cookie3' installieren, damit deine Chrome-Session")
        print("      automatisch verwendet wird (du bist auf repeaterbook.com eingeloggt).\n")

    print("Lade Repeater-Daten …")
    country_data = load_all(data_dir)

    print("\nBaue Schweizer Kanäle …")
    ch_rows, next_loc = build_swiss_rows(country_data.get("Switzerland", []))

    print(f"\nBaue Nachbarland-Kanäle (Start bei Kanal {next_loc}) …")
    nb_rows = build_neighbour_rows(country_data, next_loc)

    all_rows = ch_rows + nb_rows

    out = "CH_Repeaters_FT3DE.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CHIRP_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"  Gesamt: {len(all_rows)} Kanäle → {out}")
    print(f"{'─'*65}")

    print("\n  Schweiz — Grossregionen:")
    region_counts: dict[str, int] = {}
    for row in ch_rows:
        r = row["Comment"].split(" | ")[0]
        region_counts[r] = region_counts.get(r, 0) + 1
    for name, rdata in GROSSREGIONEN.items():
        count = region_counts.get(name, 0)
        start = rdata["start"]
        cants = ", ".join(rdata["cantons"])
        print(f"    {name:<25} {count:>4} Rep.  Kanal {start:>3}–{start+count-1:<3}  ({cants})")

    print("\n  Nachbarländer:")
    nb_country_counts: dict[str, int] = {}
    for row in nb_rows:
        label = COUNTRY_LABEL.get(
            next((c for c in NEIGHBOUR_COUNTRIES if COUNTRY_LABEL[c] in row["Comment"]), "?"), "?")
        nb_country_counts[label] = nb_country_counts.get(label, 0) + 1
    for country in NEIGHBOUR_COUNTRIES:
        label = COUNTRY_LABEL[country]
        count = nb_country_counts.get(label, 0)
        print(f"    {label:<25} {count:>4} Rep.")

    print(f"\n  Import in CHIRP: File ▸ Import ▸ {out}")

    if not data_dir:
        print("\n  Falls Fehler beim Live-Abruf:")
        print("  1. Im Browser auf repeaterbook.com einloggen")
        print("  2. Diese URLs öffnen und als <Land>.json speichern:")
        for c in ["Switzerland"] + NEIGHBOUR_COUNTRIES:
            print(f"     https://www.repeaterbook.com/api/exportROW.php?country={c}&format=json")
        print(f"  3. Alle JSON-Dateien in einen Ordner legen, z.B. data/")
        print(f"  4. python {sys.argv[0]} data/")

if __name__ == "__main__":
    main()
