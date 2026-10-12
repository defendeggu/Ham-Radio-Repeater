#!/usr/bin/env python3
"""
Swiss + Neighbouring Repeater CHIRP CSV Generator — Yaesu FT3DE
Reads Swiss repeaters from RepeaterBook.com, organises them by Grossregion,
and appends repeaters from DE/FR/IT/AT/LI within 50 km of the Swiss border,
grouped by country.

Usage:
  python repeater_chirp_ft3de.py data/             # read pre-downloaded JSON files from a folder
                                                   # (Switzerland.json, Germany.json, France.json, ...)
  python repeater_chirp_ft3de.py --token TOKEN --contact you@example.org
                                                   # live fetch via RepeaterBook API (approved token)
  python repeater_chirp_ft3de.py --help            # all options

Requirements: Python 3.9+, no third-party packages.
"""

import argparse, csv, json, math, os, re, sys, time, unicodedata
import urllib.error, urllib.parse, urllib.request
from dataclasses import dataclass
from typing import Optional

from swiss_border import SWISS_BORDER

VERSION = "2.0"

# ── Swiss Grossregionen ────────────────────────────────────────────────────────
# FT3DE memory channels are numbered 1–900.
GROSSREGIONEN: dict[str, dict] = {
    "Genferseeregion":   {"cantons": ["GE", "VD", "VS"],                          "start": 1},
    "Espace Mittelland": {"cantons": ["BE", "FR", "SO", "NE", "JU"],              "start": 100},
    "Nordwestschweiz":   {"cantons": ["AG", "BL", "BS"],                          "start": 200},
    "Zuerich":           {"cantons": ["ZH"],                                       "start": 270},
    "Ostschweiz":        {"cantons": ["GL", "SH", "AR", "AI", "SG", "GR", "TG"], "start": 320},
    "Zentralschweiz":    {"cantons": ["LU", "UR", "SZ", "OW", "NW", "ZG"],       "start": 500},
    "Tessin":            {"cantons": ["TI"],                                       "start": 580},
}

# Neighbouring countries — channel blocks follow directly after Switzerland
NEIGHBOUR_COUNTRIES: list[str] = ["France", "Germany", "Austria", "Italy", "Liechtenstein"]

COUNTRY_LABEL: dict[str, str] = {
    "France":        "Frankreich",
    "Germany":       "Deutschland",
    "Austria":       "Oesterreich",
    "Italy":         "Italien",
    "Liechtenstein": "Liechtenstein",
}

# ── Canton name → abbreviation ─────────────────────────────────────────────────
# Keys are normalised with norm_name() (lowercase, no accents, single spaces).
CANTON_MAP: dict[str, str] = {
    "geneva": "GE", "geneve": "GE", "genf": "GE", "ginevra": "GE",
    "vaud": "VD", "waadt": "VD",
    "valais": "VS", "wallis": "VS", "vallese": "VS",
    "bern": "BE", "berne": "BE", "berna": "BE",
    "fribourg": "FR", "freiburg": "FR", "friburgo": "FR",
    "solothurn": "SO", "soleure": "SO", "soletta": "SO",
    "neuchatel": "NE", "neuenburg": "NE",
    "jura": "JU", "giura": "JU",
    "aargau": "AG", "argovia": "AG", "argovie": "AG",
    "basel-landschaft": "BL", "basel-land": "BL", "baselland": "BL", "basel landschaft": "BL",
    "bale-campagne": "BL",
    "basel-stadt": "BS", "basel stadt": "BS", "basel": "BS", "bale-ville": "BS", "bale": "BS",
    "glarus": "GL", "glaris": "GL",
    "schaffhausen": "SH", "schaffhouse": "SH", "sciaffusa": "SH",
    "appenzell ausserrhoden": "AR", "appenzell a.rh.": "AR", "appenzell rhodes-exterieures": "AR",
    "appenzell innerrhoden": "AI", "appenzell i.rh.": "AI", "appenzell rhodes-interieures": "AI",
    "appenzell": "AI",
    "st. gallen": "SG", "st gallen": "SG", "sankt gallen": "SG", "saint-gall": "SG",
    "san gallo": "SG",
    "graubunden": "GR", "graubuenden": "GR", "grisons": "GR", "grigioni": "GR", "grischun": "GR",
    "thurgau": "TG", "thurgovie": "TG", "turgovia": "TG",
    "lucerne": "LU", "luzern": "LU", "lucerna": "LU",
    "uri": "UR", "schwyz": "SZ", "svitto": "SZ",
    "obwalden": "OW", "obwald": "OW", "nidwalden": "NW", "nidwald": "NW",
    "zug": "ZG", "zoug": "ZG", "zugo": "ZG",
    "ticino": "TI", "tessin": "TI",
    "zurich": "ZH", "zuerich": "ZH", "zurigo": "ZH",
}
CANTON_CODES = {c for r in GROSSREGIONEN.values() for c in r["cantons"]}

BORDER_MAX_KM = 50.0    # include foreign repeaters within this distance

# Bounding box with generous buffer — quick pre-filter before the distance check
BB_LAT = (45.25, 48.35)
BB_LON = (5.30, 11.20)

# FT3DE can transmit on 2 m and 70 cm only
BANDS_MHZ: list[tuple[float, float]] = [(144.0, 146.0), (430.0, 440.0)]

MAX_CHANNELS = 900

# CHIRP's standard CTCSS tones and DCS codes (chirp/chirp_common.py)
CTCSS_TONES = [
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 97.4, 100.0,
    103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2,
    151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8, 177.3, 179.9, 183.5,
    186.2, 189.9, 192.8, 196.6, 199.5, 203.5, 206.5, 210.7, 218.1, 225.7, 229.1,
    233.6, 241.8, 250.3, 254.1,
]
DCS_CODES = [
    23, 25, 26, 31, 32, 36, 43, 47, 51, 53, 54, 65, 71, 72, 73, 74, 114, 115, 116,
    122, 125, 131, 132, 134, 143, 145, 152, 155, 156, 162, 165, 172, 174, 205, 212,
    223, 225, 226, 243, 244, 245, 246, 251, 252, 255, 261, 263, 265, 266, 271, 274,
    306, 311, 315, 325, 331, 332, 343, 346, 351, 356, 364, 365, 371, 411, 412, 413,
    423, 431, 432, 445, 446, 452, 454, 455, 462, 464, 465, 466, 503, 506, 516, 523,
    526, 532, 546, 565, 606, 612, 624, 627, 631, 632, 654, 662, 664, 703, 712, 723,
    731, 732, 734, 743, 754,
]

CHIRP_FIELDS = [
    "Location", "Name", "Frequency", "Duplex", "Offset", "Tone",
    "rToneFreq", "cToneFreq", "DtcsCode", "DtcsPolarity", "Mode",
    "TStep", "Skip", "Comment", "URCALL", "RPT1CALL", "RPT2CALL", "DVCODE",
]

NAME_LEN = 16   # FT1D/FT3D memory name length in CHIRP

API_URL = "https://www.repeaterbook.com/api/exportROW.php"

# ── Geometry ───────────────────────────────────────────────────────────────────

EARTH_R = 6371.0

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return EARTH_R * 2 * math.asin(math.sqrt(a))

def point_in_polygon(lat: float, lon: float, poly: list[tuple[float, float]]) -> bool:
    """Ray casting test; poly is a closed ring of (lat, lon) points."""
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside

def _segment_dist_km(lat: float, lon: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance from a point to segment a–b, using a local equirectangular projection
    centred on the point (error well below 1 % at the distances we care about)."""
    kx = math.radians(1) * EARTH_R * math.cos(math.radians(lat))
    ky = math.radians(1) * EARTH_R
    ax, ay = (a[1] - lon) * kx, (a[0] - lat) * ky
    bx, by = (b[1] - lon) * kx, (b[0] - lat) * ky
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
    return math.hypot(ax + t * dx, ay + t * dy)

def min_dist_to_ch(lat: float, lon: float) -> float:
    """Shortest distance (km) from a point to the Swiss border; 0 if inside Switzerland."""
    if point_in_polygon(lat, lon, SWISS_BORDER):
        return 0.0
    n = len(SWISS_BORDER)
    return min(_segment_dist_km(lat, lon, SWISS_BORDER[i], SWISS_BORDER[(i + 1) % n])
               for i in range(n))

def in_bounding_box(lat: float, lon: float) -> bool:
    return BB_LAT[0] <= lat <= BB_LAT[1] and BB_LON[0] <= lon <= BB_LON[1]

# ── Repeater field helpers ─────────────────────────────────────────────────────

def field(rep: dict, *keys: str) -> str:
    """First non-empty value of the given keys (also tries lowercase/underscore variants)."""
    for key in keys:
        for k in (key, key.lower(), key.lower().replace(" ", "_")):
            val = rep.get(k)
            if val not in (None, ""):
                return str(val).strip()
    return ""

def to_float(value) -> float:
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return 0.0

def is_yes(rep: dict, key: str) -> bool:
    return field(rep, key).lower() in ("yes", "true", "1")

def norm_name(name: str) -> str:
    """Lowercase, strip accents/umlauts, collapse whitespace: 'Zürich' → 'zurich'."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(ascii_only.lower().split())

def canton_abbr(state: str) -> Optional[str]:
    if state.strip().upper() in CANTON_CODES:
        return state.strip().upper()
    return CANTON_MAP.get(norm_name(state))

def grossregion(canton: Optional[str]) -> Optional[str]:
    for name, data in GROSSREGIONEN.items():
        if canton in data["cantons"]:
            return name
    return None

def in_bands(freq_mhz: float) -> bool:
    return any(lo <= freq_mhz <= hi for lo, hi in BANDS_MHZ)

def duplex_offset(out_mhz: float, in_mhz: float) -> tuple[str, str]:
    if in_mhz <= 0 or abs(out_mhz - in_mhz) < 1e-6:
        return "", "0.00000"
    return ("-" if in_mhz < out_mhz else "+"), f"{abs(out_mhz - in_mhz):.5f}"

def parse_tone(value: str) -> tuple[str, object]:
    """'88.5' → ('Tone', 88.5), 'D023' → ('DTCS', 23), 'CSQ'/'' → ('', None)."""
    v = (value or "").strip().upper()
    m = re.match(r"^D(\d{3})", v)
    if m:
        code = int(m.group(1))
        return ("DTCS", code) if code in DCS_CODES else ("", None)
    m = re.match(r"^(\d+(?:[.,]\d+)?)", v)
    if m:
        tone = to_float(m.group(1))
        if tone in CTCSS_TONES:
            return "Tone", tone
    return "", None

def tone_fields(pl: str, tsq: str) -> dict[str, str]:
    """CHIRP tone columns from RepeaterBook's PL (uplink) and TSQ (downlink) values.
    The FT3DE supports Tone, TSQL and DTCS but no cross modes."""
    cols = {"Tone": "", "rToneFreq": "88.5", "cToneFreq": "88.5",
            "DtcsCode": "023", "DtcsPolarity": "NN"}
    kind, val = parse_tone(pl)
    tsq_kind, tsq_val = parse_tone(tsq)
    if kind == "DTCS":
        cols.update(Tone="DTCS", DtcsCode=f"{val:03d}")
    elif kind == "Tone":
        if tsq_kind == "Tone" and tsq_val == val:
            cols.update(Tone="TSQL", rToneFreq=str(val), cToneFreq=str(val))
        else:
            cols.update(Tone="Tone", rToneFreq=str(val))
    return cols

def tuning_step(freq_mhz: float) -> str:
    hz = round(freq_mhz * 1_000_000)
    for step_hz, label in ((12_500, "12.5"), (6_250, "6.25"), (5_000, "5.0")):
        if hz % step_hz == 0:
            return label
    return "12.5"

def rep_coords(rep: dict) -> tuple[float, float]:
    return to_float(field(rep, "Lat")), to_float(field(rep, "Long", "Lon"))

# ── Repeater model ─────────────────────────────────────────────────────────────

@dataclass
class Repeater:
    freq: float
    input_freq: float
    callsign: str
    city: str
    state: str
    lat: float
    lon: float
    fusion: bool
    narrow: bool
    tones: dict

    @property
    def key(self) -> tuple[float, str]:
        return round(self.freq, 4), self.callsign.upper()

def parse_repeater(rep: dict, include_closed: bool = False,
                   include_offair: bool = False) -> tuple[Optional[Repeater], str]:
    """Returns (Repeater, "") or (None, skip reason)."""
    freq = to_float(field(rep, "Frequency"))
    if freq <= 0:
        return None, "keine Frequenz"
    if not in_bands(freq):
        return None, "nicht 2 m / 70 cm"

    status = field(rep, "Operational Status").lower()
    if not include_offair and status in ("off-air", "off air"):
        return None, "ausser Betrieb"

    use = field(rep, "Use").upper()
    if not include_closed and use in ("CLOSED", "PRIVATE"):
        return None, "geschlossen/privat"

    # Mode: keep analogue FM and C4FM (Fusion). Pure DMR / D-STAR / NXDN / … are
    # useless on the FT3DE. Records without any mode flags are kept.
    mode_keys = ("FM Analog", "System Fusion", "DMR", "D-Star", "NXDN", "APCO P-25", "M17", "Tetra")
    has_flags = any(field(rep, k) for k in mode_keys)
    fm, fusion = is_yes(rep, "FM Analog"), is_yes(rep, "System Fusion")
    if has_flags and not (fm or fusion):
        return None, "nur digital (kein FM/C4FM)"

    bandwidth = field(rep, "FM Bandwidth").lower()
    narrow = "narrow" in bandwidth or "12.5" in bandwidth

    lat, lon = rep_coords(rep)
    return Repeater(
        freq=freq,
        input_freq=to_float(field(rep, "Input Freq")),
        callsign=field(rep, "Callsign")[:NAME_LEN],
        city=field(rep, "Nearest City", "Landmark"),
        state=field(rep, "State", "Region"),
        lat=lat, lon=lon,
        fusion=fusion,
        narrow=narrow,
        tones=tone_fields(field(rep, "PL"), field(rep, "TSQ")),
    ), ""

def join_comment(*parts: str) -> str:
    return " | ".join(p for p in parts if p)

def make_row(loc: int, rep: Repeater, comment: str) -> dict:
    duplex, offset = duplex_offset(rep.freq, rep.input_freq)
    if rep.fusion:
        comment += " | C4FM"
    return {
        "Location":  loc,
        "Name":      rep.callsign,
        "Frequency": f"{rep.freq:.5f}",
        "Duplex":    duplex,
        "Offset":    offset,
        **rep.tones,
        # FM and C4FM both run as FM on the FT3DE (AMS switches automatically)
        "Mode":      "NFM" if rep.narrow else "FM",
        "TStep":     tuning_step(rep.freq),
        "Skip":      "",
        "Comment":   comment,
        "URCALL":    "",
        "RPT1CALL":  "",
        "RPT2CALL":  "",
        "DVCODE":    "",
    }

# ── Load data (live or from folder) ───────────────────────────────────────────

def extract_repeaters(raw, source: str) -> list[dict]:
    """Normalises a RepeaterBook payload to a list of repeater dicts.
    Raises ValueError for error responses or unknown formats."""
    if isinstance(raw, dict):
        if raw.get("ok") is False or "error_code" in raw or raw.get("status") == "error":
            msg = raw.get("message") or raw.get("error_code") or raw
            raise ValueError(f"{source}: API-Fehler: {msg}")
        for key in ("results", "repeaters", "data"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            raise ValueError(f"{source}: unbekanntes Format (Schlüssel: {', '.join(list(raw)[:8])})")
    if not isinstance(raw, list):
        raise ValueError(f"{source}: unbekanntes Format ({type(raw).__name__})")
    return [r for r in raw if isinstance(r, dict)]

def user_agent(contact: str) -> str:
    return (f"Ham-Radio-Repeater-CHIRP/{VERSION} "
            f"(+https://github.com/defendeggu/Ham-Radio-Repeater; {contact})")

class StopFetching(RuntimeError):
    """Auth failure or rate limit — no further API requests may be sent this run."""

def fetch_country(country: str, token: str, contact: str) -> list[dict]:
    url = f"{API_URL}?{urllib.parse.urlencode({'country': country})}"
    req = urllib.request.Request(url, headers={
        "User-Agent":     user_agent(contact),
        "Accept":         "application/json",
        "X-RB-App-Token": token,
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        hint = {401: "Token fehlt oder ungültig", 403: "Zugriff verweigert (Token/User-Agent prüfen)",
                429: "Rate-Limit erreicht — später erneut versuchen"}.get(e.code, e.reason)
        error = StopFetching if e.code in (401, 403, 429) else RuntimeError
        raise error(f"HTTP {e.code}: {hint}") from None
    return extract_repeaters(raw, country)

def load_from_folder(data_dir: str, countries: list[str]) -> dict[str, list]:
    result: dict[str, list] = {}
    for country in countries:
        for name in (f"{country}.json", f"{country.lower()}.json"):
            path = os.path.join(data_dir, name)
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        reps = extract_repeaters(json.load(f), name)
                except (ValueError, json.JSONDecodeError) as exc:
                    print(f"  {country:<15}: FEHLER in {name}: {exc}")
                    reps = []
                result[country] = reps
                print(f"  {country:<15}: {len(reps):>4} Repeater aus {name}")
                break
        else:
            print(f"  {country:<15}: keine Datei gefunden (übersprungen)")
    return result

def load_live(countries: list[str], token: str, contact: str) -> dict[str, list]:
    result: dict[str, list] = {}
    for i, country in enumerate(countries):
        if i:
            time.sleep(1.2)   # be polite to the server
        print(f"  Lade {country} ...", end=" ", flush=True)
        try:
            result[country] = fetch_country(country, token, contact)
            print(f"{len(result[country])} Repeater")
        except StopFetching as exc:
            print(f"FEHLER: {exc}")
            print("  Abbruch: keine weiteren API-Requests in diesem Lauf.")
            break
        except Exception as exc:
            print(f"FEHLER: {exc}")
            result[country] = []
    return result

# ── Build CHIRP rows ───────────────────────────────────────────────────────────

@dataclass
class Group:
    label: str
    detail: str
    first: int = 0
    count: int = 0

    @property
    def range_text(self) -> str:
        return f"{self.first:>3}–{self.first + self.count - 1:<3}" if self.count else "   –   "

class Builder:
    def __init__(self, include_closed: bool = False, include_offair: bool = False):
        self.include_closed = include_closed
        self.include_offair = include_offair
        self.skipped: dict[str, int] = {}
        self.unknown_cantons: dict[str, int] = {}
        self.seen: set[tuple[float, str]] = set()
        self.duplicates = 0

    def _skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def _parse(self, raw: dict) -> Optional[Repeater]:
        rep, reason = parse_repeater(raw, self.include_closed, self.include_offair)
        if rep is None:
            self._skip(reason)
            return None
        if rep.key in self.seen:
            self.duplicates += 1
            return None
        self.seen.add(rep.key)
        return rep

    def swiss_rows(self, repeaters: list[dict], max_channels: int) -> tuple[list, list[Group], int]:
        """Returns (rows, groups, next_free_location)."""
        by_region: dict[str, list] = {r: [] for r in GROSSREGIONEN}
        for raw in repeaters:
            rep = self._parse(raw)
            if rep is None:
                continue
            canton = canton_abbr(rep.state)
            region = grossregion(canton)
            if region:
                by_region[region].append((canton, rep))
            else:
                name = rep.state or "(leer)"
                self.unknown_cantons[name] = self.unknown_cantons.get(name, 0) + 1

        rows, groups = [], []
        next_loc = 1
        for region_name, rdata in GROSSREGIONEN.items():
            group = Group(region_name, ", ".join(rdata["cantons"]))
            groups.append(group)
            # never collide with the previous region if that one overflowed its block
            loc = max(rdata["start"], next_loc)
            group.first = loc
            for canton, rep in sorted(by_region[region_name], key=lambda x: x[1].freq):
                if loc > max_channels:
                    self._skip(f"über {max_channels} Kanäle")
                    continue
                rows.append(make_row(loc, rep, join_comment(region_name, canton, rep.city)))
                group.count += 1
                loc += 1
            next_loc = loc
        return rows, groups, next_loc

    def neighbour_rows(self, country_data: dict[str, list], countries: list[str], start_loc: int,
                       max_channels: int, radius_km: float) -> tuple[list, list[Group]]:
        """Filter by proximity and build rows grouped by country. If not all fit,
        the repeaters farthest from the border are dropped first."""
        candidates = []   # (dist, country, rep)
        totals: dict[str, int] = {}
        for country in countries:
            repeaters = country_data.get(country, [])
            totals[country] = len(repeaters)
            for raw in repeaters:
                lat, lon = rep_coords(raw)
                if (lat == 0 and lon == 0) or not in_bounding_box(lat, lon):
                    continue
                dist = min_dist_to_ch(lat, lon)
                if dist > radius_km:
                    continue
                rep = self._parse(raw)
                if rep is not None:
                    candidates.append((dist, country, rep))

        capacity = max(0, max_channels - start_loc + 1)
        if len(candidates) > capacity:
            candidates.sort(key=lambda c: c[0])
            for _ in candidates[capacity:]:
                self._skip(f"über {max_channels} Kanäle")
            candidates = candidates[:capacity]

        rows, groups = [], []
        loc = start_loc
        for country in countries:
            label = COUNTRY_LABEL[country]
            nearby = sorted((c for c in candidates if c[1] == country), key=lambda c: c[2].freq)
            print(f"  {country:<15}: {len(nearby):>4} Repeater innerhalb {radius_km:.0f} km "
                  f"(von {totals[country]} gesamt)")
            group = Group(label, f"≤ {radius_km:.0f} km", first=loc)
            groups.append(group)
            for dist, _, rep in nearby:
                rows.append(make_row(loc, rep, join_comment(label, rep.state, rep.city, f"{dist:.0f} km")))
                group.count += 1
                loc += 1
        return rows, groups

# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Erstellt eine CHIRP-CSV mit Schweizer Repeatern (+ Nachbarländer) für das Yaesu FT3DE.")
    p.add_argument("data_dir", nargs="?",
                   help="Ordner mit <Land>.json-Dateien; ohne Angabe wird live abgerufen")
    p.add_argument("-o", "--output", default="CH_Repeaters_FT3DE.csv", help="Ausgabedatei (Default: %(default)s)")
    p.add_argument("--radius", type=float, default=BORDER_MAX_KM,
                   help="Max. Distanz der Nachbarland-Repeater zur Grenze in km (Default: %(default)s)")
    p.add_argument("--countries", default=",".join(NEIGHBOUR_COUNTRIES),
                   help="Nachbarländer, kommagetrennt (Default: %(default)s)")
    p.add_argument("--max-channels", type=int, default=MAX_CHANNELS,
                   help="Anzahl Speicherplätze (Default: %(default)s)")
    p.add_argument("--include-closed", action="store_true", help="auch geschlossene/private Repeater")
    p.add_argument("--include-offair", action="store_true", help="auch Repeater ausser Betrieb")
    p.add_argument("--token", default=os.environ.get("RB_APP_TOKEN", ""),
                   help="RepeaterBook App-Token (oder Umgebungsvariable RB_APP_TOKEN)")
    p.add_argument("--contact", default=os.environ.get("RB_CONTACT", ""),
                   help="Kontakt-E-Mail für den User-Agent (oder RB_CONTACT)")
    args = p.parse_args(argv)

    if args.data_dir and not os.path.isdir(args.data_dir):
        p.error(f"'{args.data_dir}' ist kein Verzeichnis")
    countries = [c.strip() for c in args.countries.split(",") if c.strip()]
    unknown = [c for c in countries if c not in COUNTRY_LABEL]
    if unknown:
        p.error(f"unbekannte Länder: {', '.join(unknown)} (erlaubt: {', '.join(NEIGHBOUR_COUNTRIES)})")
    args.countries = countries
    if not args.data_dir and not (args.token and args.contact):
        p.error("Live-Abruf braucht --token und --contact (RepeaterBook-API erfordert seit 2026 "
                "ein freigegebenes App-Token). Alternativ JSON-Dateien herunterladen und "
                "den Ordner angeben, siehe README.")
    return args

def print_manual_hint(script: str) -> None:
    print("\n  Falls der Live-Abruf scheitert:")
    print("  1. Im Browser auf repeaterbook.com einloggen")
    print("  2. Diese URLs öffnen und als <Land>.json speichern:")
    for c in ["Switzerland"] + NEIGHBOUR_COUNTRIES:
        print(f"     {API_URL}?country={c}")
    print("  3. Alle JSON-Dateien in einen Ordner legen, z.B. data/")
    print(f"  4. python {script} data/")

def main(argv: Optional[list[str]] = None) -> int:
    # Windows consoles/pipes often use cp1252, which cannot encode "─" or "▸"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    args = parse_args(argv)
    all_countries = ["Switzerland"] + args.countries
    print("Lade Repeater-Daten …")
    if args.data_dir:
        country_data = load_from_folder(args.data_dir, all_countries)
    else:
        country_data = load_live(all_countries, args.token, args.contact)

    builder = Builder(args.include_closed, args.include_offair)

    print("\nBaue Schweizer Kanäle …")
    ch_rows, ch_groups, next_loc = builder.swiss_rows(country_data.get("Switzerland", []),
                                                      args.max_channels)
    if builder.unknown_cantons:
        names = ", ".join(f"{n} ({c})" for n, c in sorted(builder.unknown_cantons.items()))
        print(f"  Ohne Kanton-Zuordnung übersprungen: {names}")

    print(f"\nBaue Nachbarland-Kanäle (Start bei Kanal {next_loc}) …")
    nb_rows, nb_groups = builder.neighbour_rows(country_data, args.countries, next_loc, args.max_channels, args.radius)

    all_rows = ch_rows + nb_rows
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CHIRP_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"  Gesamt: {len(all_rows)} Kanäle → {args.output}")
    print(f"{'─'*65}")
    for title, groups in (("Schweiz — Grossregionen", ch_groups), ("Nachbarländer", nb_groups)):
        print(f"\n  {title}:")
        for g in groups:
            print(f"    {g.label:<25} {g.count:>4} Rep.  Kanal {g.range_text}  ({g.detail})")

    if builder.skipped or builder.duplicates:
        print("\n  Übersprungen:")
        for reason, count in sorted(builder.skipped.items(), key=lambda x: -x[1]):
            print(f"    {reason:<30} {count:>4}")
        if builder.duplicates:
            print(f"    {'Duplikat':<30} {builder.duplicates:>4}")

    print(f"\n  Import in CHIRP: File ▸ Import ▸ {args.output}")
    print("\n  Data courtesy of RepeaterBook.com. — https://www.repeaterbook.com/")
    if not args.data_dir and not any(country_data.values()):
        print_manual_hint(os.path.basename(sys.argv[0]))
    return 0

if __name__ == "__main__":
    sys.exit(main())
