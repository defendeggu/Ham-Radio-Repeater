import contextlib, csv, io, json, os, tempfile, unittest

import repeater_chirp_ft3de as gen


def rb(freq, inp=None, **extra):
    """Minimal RepeaterBook-style record."""
    rep = {"Frequency": str(freq), "Input Freq": str(inp if inp is not None else freq),
           "Callsign": "HB9XX", "Nearest City": "Testdorf", "State": "Bern",
           "Operational Status": "On-air", "Use": "OPEN", "FM Analog": "Yes"}
    rep.update(extra)
    return rep


class HelperTests(unittest.TestCase):
    def test_duplex_offset(self):
        self.assertEqual(gen.duplex_offset(145.6, 145.0), ("-", "0.60000"))
        self.assertEqual(gen.duplex_offset(430.4, 438.0), ("+", "7.60000"))
        self.assertEqual(gen.duplex_offset(145.5, 145.5), ("", "0.00000"))
        self.assertEqual(gen.duplex_offset(145.5, 0), ("", "0.00000"))

    def test_tones(self):
        self.assertEqual(gen.tone_fields("88.5", "")["Tone"], "Tone")
        tsql = gen.tone_fields("71.9", "71.9")
        self.assertEqual((tsql["Tone"], tsql["cToneFreq"]), ("TSQL", "71.9"))
        self.assertEqual(gen.tone_fields("71.9", "123.0")["Tone"], "Tone")
        dcs = gen.tone_fields("D023", "")
        self.assertEqual((dcs["Tone"], dcs["DtcsCode"]), ("DTCS", "023"))
        self.assertEqual(gen.tone_fields("CSQ", "")["Tone"], "")
        self.assertEqual(gen.tone_fields("88.4", "")["Tone"], "")   # not a standard tone
        self.assertEqual(gen.tone_fields("", "")["Tone"], "")

    def test_canton_names_with_accents(self):
        self.assertEqual(gen.canton_abbr("Zürich"), "ZH")
        self.assertEqual(gen.canton_abbr("Graubünden"), "GR")
        self.assertEqual(gen.canton_abbr("Neuchâtel"), "NE")
        self.assertEqual(gen.canton_abbr("Genève"), "GE")
        self.assertEqual(gen.canton_abbr("  st.  gallen "), "SG")
        self.assertEqual(gen.canton_abbr("TI"), "TI")
        self.assertIsNone(gen.canton_abbr("Atlantis"))

    def test_tuning_step(self):
        self.assertEqual(gen.tuning_step(145.6), "12.5")
        self.assertEqual(gen.tuning_step(438.68125), "6.25")

    def test_extract_repeaters(self):
        self.assertEqual(gen.extract_repeaters({"results": [{"a": 1}, "junk"]}, "x"), [{"a": 1}])
        self.assertEqual(gen.extract_repeaters([{"a": 1}], "x"), [{"a": 1}])
        with self.assertRaises(ValueError):
            gen.extract_repeaters({"ok": False, "error_code": "auth_missing"}, "x")
        with self.assertRaises(ValueError):
            gen.extract_repeaters({"count": 0}, "x")


class FilterTests(unittest.TestCase):
    def parse(self, rep, **kw):
        return gen.parse_repeater(rep, **kw)

    def test_keeps_fm_and_fusion(self):
        rep, _ = self.parse(rb(145.6, 145.0))
        self.assertIsNotNone(rep)
        rep, _ = self.parse(rb(439.0, 431.4, **{"FM Analog": "No", "System Fusion": "Yes"}))
        self.assertTrue(rep.fusion)
        self.assertIn("C4FM", gen.make_row(1, rep, "x")["Comment"])

    def test_drops_digital_only(self):
        for mode in ("DMR", "D-Star", "NXDN"):
            rep, reason = self.parse(rb(439.0, 431.4, **{"FM Analog": "No", mode: "Yes"}))
            self.assertIsNone(rep, mode)
            self.assertIn("digital", reason)

    def test_record_without_mode_flags_is_kept(self):
        rep, _ = self.parse({"Frequency": "145.6", "Input Freq": "145.0"})
        self.assertIsNotNone(rep)

    def test_band_status_and_use(self):
        self.assertIsNone(self.parse(rb(1297.0, 1291.0))[0])
        self.assertIsNone(self.parse(rb(29.66, 29.56))[0])
        self.assertIsNone(self.parse(rb(145.6, 145.0, **{"Operational Status": "Off-air"}))[0])
        self.assertIsNotNone(self.parse(rb(145.6, 145.0, **{"Operational Status": "Off-air"}),
                                        include_offair=True)[0])
        self.assertIsNone(self.parse(rb(145.6, 145.0, Use="CLOSED"))[0])
        self.assertIsNotNone(self.parse(rb(145.6, 145.0, Use="CLOSED"), include_closed=True)[0])

    def test_narrow_fm(self):
        rep, _ = self.parse(rb(438.6875, 431.0875, **{"FM Bandwidth": "Narrow"}))
        self.assertEqual(gen.make_row(1, rep, "x")["Mode"], "NFM")


class BorderTests(unittest.TestCase):
    def test_inside_switzerland(self):
        self.assertEqual(gen.min_dist_to_ch(46.948, 7.447), 0.0)      # Bern
        self.assertEqual(gen.min_dist_to_ch(46.004, 8.951), 0.0)      # Lugano

    def test_near_border(self):
        self.assertLess(gen.min_dist_to_ch(47.663, 9.175), 5)         # Konstanz
        self.assertLess(gen.min_dist_to_ch(46.687, 10.550), 15)       # Mals (Vinschgau)
        self.assertLess(gen.min_dist_to_ch(46.903, 6.355), 10)        # Pontarlier
        self.assertTrue(25 < gen.min_dist_to_ch(45.464, 9.190) < 50)  # Milano

    def test_far_away(self):
        self.assertGreater(gen.min_dist_to_ch(48.137, 11.575), 100)   # München
        self.assertGreater(gen.min_dist_to_ch(45.764, 4.836), 90)     # Lyon


class BuilderTests(unittest.TestCase):
    def build(self, swiss, neighbours, max_channels=900, countries=("Germany",)):
        b = gen.Builder()
        with contextlib.redirect_stdout(io.StringIO()):
            ch_rows, ch_groups, next_loc = b.swiss_rows(swiss, max_channels)
            nb_rows, nb_groups = b.neighbour_rows(neighbours, list(countries), next_loc,
                                                  max_channels, 50.0)
        return b, ch_rows, nb_rows, ch_groups, nb_groups

    def test_layout_starts_at_one(self):
        swiss = [rb(145.6, 145.0, State="Genève", Callsign="HB9GE"),
                 rb(145.7, 145.1, State="Zürich", Callsign="HB9ZH"),
                 rb(145.6, 145.0, State="Nowhere", Callsign="HB9NO")]
        b, ch_rows, _, groups, _ = self.build(swiss, {})
        self.assertEqual([r["Location"] for r in ch_rows], [1, 270])
        self.assertEqual(ch_rows[0]["Comment"], "Genferseeregion | GE | Testdorf")
        self.assertEqual(b.unknown_cantons, {"Nowhere": 1})
        self.assertEqual(groups[0].range_text.strip(), "1–1")
        self.assertEqual(groups[1].range_text.strip(), "–")

    def test_neighbours_follow_swiss_and_duplicates_dropped(self):
        swiss = [rb(145.6, 145.0, State="TI", Callsign="HB9TI")]
        de = [rb(145.65, 145.05, State="Baden-Württemberg", Callsign="DB0KN", Lat="47.66", Long="9.17"),
              rb(145.65, 145.05, State="Baden-Württemberg", Callsign="DB0KN", Lat="47.66", Long="9.17"),
              rb(145.7, 145.1, State="Bayern", Callsign="DB0MU", Lat="48.14", Long="11.0")]
        b, ch_rows, nb_rows, _, _ = self.build(swiss, {"Germany": de})
        self.assertEqual(ch_rows[0]["Location"], 580)
        self.assertEqual([r["Location"] for r in nb_rows], [581])
        self.assertTrue(nb_rows[0]["Comment"].startswith("Deutschland | Baden-Württemberg | Testdorf | "))
        self.assertEqual(b.duplicates, 1)

    def test_channel_limit_drops_farthest_neighbours(self):
        swiss = [rb(145.6, 145.0, State="TI", Callsign="HB9TI")]   # → channel 580
        de = [rb(145.6125 + i * 0.0125, 145.0, State="BW", Callsign=f"DB0X{i}",
                 Lat=str(47.70 + i * 0.05), Long="8.6") for i in range(5)]
        b, _, nb_rows, _, _ = self.build(swiss, {"Germany": de}, max_channels=583)
        self.assertEqual([r["Location"] for r in nb_rows], [581, 582, 583])
        self.assertEqual({r["Name"] for r in nb_rows}, {"DB0X0", "DB0X1", "DB0X2"})
        self.assertEqual(b.skipped.get("über 583 Kanäle"), 2)


class MainTests(unittest.TestCase):
    def test_folder_run_writes_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "Switzerland.json"), "w", encoding="utf-8") as f:
                json.dump({"results": [rb(145.6, 145.0, State="Bern", PL="71.9")]}, f)
            with open(os.path.join(tmp, "Germany.json"), "w", encoding="utf-8") as f:
                json.dump({"ok": False, "error_code": "auth_missing"}, f)
            out = os.path.join(tmp, "out.csv")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gen.main([tmp, "-o", out]), 0)
            with open(out, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Location"], "100")
        self.assertEqual((rows[0]["Tone"], rows[0]["rToneFreq"]), ("Tone", "71.9"))

    def test_live_requires_token_and_contact(self):
        env = {k: os.environ.pop(k) for k in ("RB_APP_TOKEN", "RB_CONTACT") if k in os.environ}
        try:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                gen.parse_args([])
        finally:
            os.environ.update(env)


if __name__ == "__main__":
    unittest.main()
