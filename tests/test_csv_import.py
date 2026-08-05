import os
import unittest

from _bootstrap import FIXTURES  # noqa: F401 (also bootstraps sys.path)

from provenmetal_kicad.bom import parse_bom_csv
from provenmetal_kicad.grouping import group_rows
from provenmetal_kicad import fields


class TestCsvHeaderMapping(unittest.TestCase):
    def test_maps_common_headers(self):
        row = fields.map_csv_row(
            {"Reference": "C1,C5", "Value": "10u", "Footprint": "C_0603",
             "QUANTITY": "2", "Manufacturer": "Murata", "MPN": "GRM188R61C106KAALD",
             "Description": "10uF", "Sourcing": "Buy"}
        )
        self.assertEqual(row["mpn"], "GRM188R61C106KAALD")
        self.assertEqual(row["manufacturer"], "Murata")
        self.assertEqual(row["qty"], "2")
        self.assertEqual(row["reference"], "C1,C5")

    def test_field_map_override(self):
        row = fields.map_csv_row(
            {"Part No": "ABC123", "Value": "10k"},
            field_map={"mpn": "Part No"},
        )
        self.assertEqual(row["mpn"], "ABC123")


class TestPgGiftCsv(unittest.TestCase):
    """The pg-gift BOM keeps MPNs in a generated CSV (not the schematic)."""

    def setUp(self):
        path = os.path.join(FIXTURES, "pg-gift-bom.csv")
        self.extract = parse_bom_csv(path)
        self.lines = group_rows(self.extract.rows, exclude_dnp=True)
        self.by_key = {ln["line_key"]: ln for ln in self.lines}

    def test_mpns_are_read(self):
        # Real MPNs come through as line keys.
        self.assertIn("grm188r61c106kaald", self.by_key)
        line = self.by_key["grm188r61c106kaald"]
        self.assertEqual(line["manufacturer"], "Murata")
        self.assertEqual(sorted(line["references"]), ["C1", "C5"])

    def test_description_is_captured(self):
        # Description is what lets Bob source no-MPN passives; it must flow through.
        line = self.by_key["grm188r61c106kaald"]
        self.assertIn("10", line["description"])
        self.assertTrue(line["description"])

    def test_testpoint_placeholder_mpn_dropped(self):
        # Test points have MPN "—" in the BOM -> keyed by value, not the dash.
        for ln in self.lines:
            self.assertNotIn(ln["line_key"], ("\u2014", "-", ""))

    def test_every_line_has_orderable_identity(self):
        for ln in self.lines:
            self.assertTrue(ln["mpn"] or ln["lcsc"] or ln["value"])


if __name__ == "__main__":
    unittest.main()
