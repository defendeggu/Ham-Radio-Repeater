# Ham Radio Repeater — CHIRP CSV Generator für Yaesu FT3DE

Erstellt eine CHIRP-kompatible Speicherliste für das **Yaesu FT3DE** mit allen
Schweizer Repeatern (geordnet nach Grossregion) sowie Repeatern aus den
Nachbarländern **DE · FR · IT · AT · LI** innerhalb von **50 km** der Schweizer Grenze.

Datenquelle: [RepeaterBook.com](https://www.repeaterbook.com/)

---

## Voraussetzungen

- Python **3.9** oder neuer
- keine weiteren Pakete nötig (nur Standardbibliothek)

---

## Verwendung

### Option A — JSON-Dateien aus einem Ordner (empfohlen)

1. Bei [repeaterbook.com](https://www.repeaterbook.com/) einloggen
   (Exporte sind für registrierte Benutzer erlaubt, nur für den persönlichen Gebrauch).
2. Die folgenden URLs im eingeloggten Browser öffnen und jeweils als `<Land>.json`
   in einen Ordner `data/` speichern:

| Dateiname | URL |
|---|---|
| `Switzerland.json` | `https://www.repeaterbook.com/api/exportROW.php?country=Switzerland` |
| `Germany.json` | `https://www.repeaterbook.com/api/exportROW.php?country=Germany` |
| `France.json` | `https://www.repeaterbook.com/api/exportROW.php?country=France` |
| `Italy.json` | `https://www.repeaterbook.com/api/exportROW.php?country=Italy` |
| `Austria.json` | `https://www.repeaterbook.com/api/exportROW.php?country=Austria` |
| `Liechtenstein.json` | `https://www.repeaterbook.com/api/exportROW.php?country=Liechtenstein` |

> Zeigt der Browser `{"ok":false,"error_code":"auth_missing",…}`, ist ein Export über
> die API ohne Token nicht möglich. Dann die Export-Funktion der Website verwenden
> (siehe [RepeaterBook-Wiki: Exports](https://www.repeaterbook.com/wiki/doku.php?id=exports)).
> Fehlerantworten in einer Datei werden erkannt und gemeldet, das Land wird übersprungen.

3. Skript starten:

```bash
python repeater_chirp_ft3de.py data/
```

### Option B — Live-Abruf über die RepeaterBook-API

Seit März 2026 ist die RepeaterBook-API nur noch für **freigegebene Clients mit
App-Token** zugänglich ([API-Richtlinie](https://www.repeaterbook.com/wiki/doku.php?id=api)).
Wer ein Token hat:

```bash
python repeater_chirp_ft3de.py --token <APP_TOKEN> --contact du@example.org
```

oder über Umgebungsvariablen `RB_APP_TOKEN` und `RB_CONTACT`. Die Kontaktadresse
wird — wie von RepeaterBook verlangt — im User-Agent mitgeschickt. Das Token geht
im Header `X-RB-App-Token` mit.

### Optionen

| Option | Bedeutung |
|---|---|
| `-o DATEI` | Ausgabedatei (Default `CH_Repeaters_FT3DE.csv`) |
| `--radius KM` | Max. Distanz der Nachbarland-Repeater zur Grenze (Default 50) |
| `--countries LISTE` | Nachbarländer, z.B. `Germany,Liechtenstein` |
| `--max-channels N` | Anzahl Speicherplätze (Default 900) |
| `--include-closed` | auch geschlossene/private Repeater übernehmen |
| `--include-offair` | auch Repeater ausser Betrieb übernehmen |

---

## Ausgabe

Die Datei **`CH_Repeaters_FT3DE.csv`** enthält höchstens 900 Kanäle (FT3DE-Speicher 1–900)
im CHIRP-Format und kann direkt importiert werden:

> CHIRP → **File ▸ Import** → `CH_Repeaters_FT3DE.csv`

### Kanalstruktur

#### Schweiz — nach Grossregion ([BFS-Definition](https://de.wikipedia.org/wiki/Grossregion_(Schweiz)))

| Kanal | Grossregion | Kantone |
|---|---|---|
| 1–99 | Genferseeregion | GE, VD, VS |
| 100–199 | Espace Mittelland | BE, FR, SO, NE, JU |
| 200–269 | Nordwestschweiz | AG, BL, BS |
| 270–319 | Zürich | ZH |
| 320–499 | Ostschweiz | GL, SH, AR, AI, SG, GR, TG |
| 500–579 | Zentralschweiz | LU, UR, SZ, OW, NW, ZG |
| ab 580 | Tessin | TI |

Hat eine Region mehr Repeater als ihr Block fasst, verschieben sich die folgenden
Regionen entsprechend nach hinten.

#### Nachbarländer — ≤ 50 km zur Schweizer Grenze

Die Nachbarländer folgen **direkt nach dem letzten Schweizer Kanal**, in der Reihenfolge
Frankreich, Deutschland, Österreich, Italien, Liechtenstein — innerhalb jedes Landes
nach Frequenz sortiert. Reicht der Platz bis Kanal 900 nicht, werden die am weitesten
von der Grenze entfernten Repeater weggelassen.

> Die tatsächliche Kanalverteilung wird nach jedem Lauf in der Konsole ausgegeben,
> zusammen mit der Anzahl übersprungener Repeater und dem Grund.

### Kommentarfeld

```
Schweiz:       <Grossregion> | <Kanton> | <Stadt>
Nachbarländer: <Land> | <Bundesland/Region> | <Stadt> | <Distanz> km
```

C4FM-fähige Repeater erhalten zusätzlich `| C4FM`.

---

## Was übernommen wird

- **Bänder:** nur 2 m (144–146 MHz) und 70 cm (430–440 MHz) — darauf kann das FT3DE senden
- **Betriebsarten:** analoges FM und C4FM (System Fusion). Reine DMR-, D-STAR-, NXDN-,
  P25-, M17- und TETRA-Repeater werden weggelassen.
  FM und C4FM werden als `FM` exportiert (das FT3DE schaltet per AMS automatisch um),
  Schmalband-FM als `NFM`.
- **Status:** Repeater mit Status *Off-air* sowie geschlossene/private Repeater werden
  weggelassen (siehe Optionen)
- **Töne:** CTCSS als `Tone` bzw. `TSQL` (wenn Ein- und Ausgabeton gleich), DCS als `DTCS`
- **Duplikate** (gleiche Frequenz und gleiches Rufzeichen) werden nur einmal übernommen
- **Kantonsnamen** werden in Deutsch, Französisch, Italienisch und Englisch erkannt,
  auch mit Umlauten und Akzenten. Nicht zuordenbare Namen werden in der Konsole aufgelistet.

---

## Technische Details

- **Distanzfilter:** kürzeste Distanz zum Schweizer Grenzverlauf
  ([Natural Earth](https://www.naturalearthdata.com/) 1:50m, Genauigkeit ca. 1–2 km),
  siehe [`swiss_border.py`](swiss_border.py)
- **Vorfilter:** Bounding Box `45.25–48.35°N / 5.30–11.20°E`
- **Kanalraster:** TStep wird pro Frequenz bestimmt (12.5 / 6.25 / 5 kHz)
- **Rate Limiting:** 1,2 s Pause zwischen API-Requests

### Tests

```bash
python -m unittest
```

---

## Lizenz

Der Code steht unter der [MIT-Lizenz](LICENSE).

Repeater-Daten © [RepeaterBook.com](https://www.repeaterbook.com/) — nur für den persönlichen Gebrauch.
Grenzdaten: Natural Earth (Public Domain).
