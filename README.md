# Ham Radio Repeater — CHIRP CSV Generator für Yaesu FT3DE

Erstellt eine CHIRP-kompatible Speicherliste für das **Yaesu FT3DE** mit allen
Schweizer Repeatern (geordnet nach Grossregion) sowie Repeatern aus den
Nachbarländern **DE · FR · IT · AT · LI** innerhalb von **50 km** der Schweizer Grenze.

Datenquelle: [RepeaterBook.com](https://www.repeaterbook.com/)

---

## Voraussetzungen

```bash
pip install requests
pip install browser-cookie3   # empfohlen: nutzt deine Chrome-Session automatisch
```

> **browser-cookie3** liest die Cookies deines laufenden Chrome-Browsers aus,
> sodass du dich nicht separat beim Skript anmelden musst.
> Ohne dieses Paket wird ein anonymer Request versucht (kann 403 liefern).

---

## Verwendung

### Option A — Live-Abruf (empfohlen)

1. Im Browser bei [repeaterbook.com](https://www.repeaterbook.com/) einloggen
2. Chrome offen lassen
3. Skript starten:

```bash
python repeater_chirp_ft3de.py
```

### Option B — Manuelle JSON-Downloads

Falls der Live-Abruf scheitert (403), diese URLs im eingeloggten Browser öffnen
und jeweils als `<Land>.json` in einen Ordner `data/` speichern:

| Dateiname | URL |
|---|---|
| `Switzerland.json` | `https://www.repeaterbook.com/api/exportROW.php?country=Switzerland&format=json` |
| `Germany.json` | `https://www.repeaterbook.com/api/exportROW.php?country=Germany&format=json` |
| `France.json` | `https://www.repeaterbook.com/api/exportROW.php?country=France&format=json` |
| `Italy.json` | `https://www.repeaterbook.com/api/exportROW.php?country=Italy&format=json` |
| `Austria.json` | `https://www.repeaterbook.com/api/exportROW.php?country=Austria&format=json` |
| `Liechtenstein.json` | `https://www.repeaterbook.com/api/exportROW.php?country=Liechtenstein&format=json` |

```bash
python repeater_chirp_ft3de.py data/
```

---

## Ausgabe

Die Datei **`CH_Repeaters_FT3DE.csv`** enthält bis zu 900 Kanäle (FT3DE-Maximum)
im CHIRP-Format und kann direkt importiert werden:

> CHIRP → **File ▸ Import** → `CH_Repeaters_FT3DE.csv`

### Kanalstruktur

#### Schweiz — nach Grossregion ([BFS-Definition](https://de.wikipedia.org/wiki/Grossregion_(Schweiz)))

| Kanal | Grossregion | Kantone |
|---|---|---|
| 000–099 | Genferseeregion | GE, VD, VS |
| 100–199 | Espace Mittelland | BE, FR, SO, NE, JU |
| 200–269 | Nordwestschweiz | AG, BL, BS |
| 270–319 | Zürich | ZH |
| 320–499 | Ostschweiz | GL, SH, AR, AI, SG, GR, TG |
| 500–579 | Zentralschweiz | LU, UR, SZ, OW, NW, ZG |
| 580–649 | Tessin | TI |

#### Nachbarländer — ≤ 50 km zur Schweizer Grenze

| Kanal | Land |
|---|---|
| ab 650 | Frankreich |
| — | Deutschland |
| — | Österreich |
| — | Italien |
| — | Liechtenstein |

> Die genaue Kanalverteilung hängt von der Anzahl gefundener Repeater ab
> und wird nach jedem Lauf in der Konsole ausgegeben.

### Kommentarfeld

Jeder Kanal enthält im CHIRP-Kommentarfeld:

```
<Region/Land> | <Stadt> | <Kanton/Bundesland> | <Distanz km>  ← nur Nachbarländer
```

---

## Technische Details

- **Distanzfilter:** Haversine-Formel gegen 30 Referenzpunkte entlang der Schweizer Grenze
- **Vorfilter:** Bounding Box `45.25–48.35°N / 5.30–11.20°E` für schnelle Vorselektion
- **Betriebsmodi:** FM und C4FM werden als `FM` exportiert (FT3DE AMS erkennt C4FM automatisch); D-STAR als `DV`; NFM als `NFM`
- **Rate Limiting:** 1,2 s Pause zwischen API-Requests

---

## Lizenz

Repeater-Daten © [RepeaterBook.com](https://www.repeaterbook.com/) — nur für den persönlichen Gebrauch.
