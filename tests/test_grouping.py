import csv
import os
import unittest

from _bootstrap import FIXTURES  # noqa: F401 (also bootstraps sys.path)

from provenmetal_kicad import fields
from provenmetal_kicad.grouping import group_rows, line_key_for


def _read_coalesced(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return [fields.coalesce_row(row) for row in csv.DictReader(fh)]


class TestGroupingSampleExport(unittest.TestCase):
    def setUp(self):
        self.rows = _read_coalesced(os.path.join(FIXTURES, "sample_export.csv"))
        self.lines = group_rows(self.rows, exclude_dnp=True)
        self.by_key = {ln["line_key"]: ln for ln in self.lines}

    def test_dnp_and_empty_lines_dropped(self):
        # TP1 is DNP, J1 has nothing orderable -> 3 real lines remain.
        self.assertEqual(len(self.lines), 3)

    def test_duplicate_mpn_rows_merge(self):
        line = self.by_key["rc0402fr-0710kl"]
        self.assertEqual(line["quantity_per_board"], 3)  # R1,R2 + R3
        self.assertEqual(sorted(line["references"]), ["R1", "R2", "R3"])

    def test_lcsc_only_line_keyed_by_lcsc(self):
        self.assertIn("c1525", self.by_key)
        line = self.by_key["c1525"]
        self.assertIsNone(line["mpn"])
        self.assertEqual(line["lcsc"], "C1525")
        self.assertEqual(line["quantity_per_board"], 3)

    def test_mpn_from_secondary_and_distributor_metadata(self):
        line = self.by_key["stm32h743vit6"]
        self.assertEqual(line["mpn"], "STM32H743VIT6")
        self.assertEqual(line["digikey"], "497-1234-ND")
        self.assertEqual(line["mouser"], "511-STM32")


class TestGroupingRealBom(unittest.TestCase):
    """Grouping against a real MPN BOM (columns mapped to canonical)."""

    def setUp(self):
        path = os.path.join(FIXTURES, "FlightControllerV1_MPN.csv")
        mapping = {
            "Reference": "reference",
            "Qty": "qty",
            "Value": "value",
            "Footprint": "footprint",
            "LCSC Part #": "lcsc",
            "MPN": "mpn",
        }
        rows = []
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            for raw in csv.DictReader(fh):
                rows.append({mapping[k]: (v or "") for k, v in raw.items() if k in mapping})
        self.lines = group_rows(rows, exclude_dnp=True)

    def test_produces_lines(self):
        self.assertGreater(len(self.lines), 10)

    def test_multi_ref_capacitor_line(self):
        # The 100n line groups 21 references at qty 21.
        target = next(ln for ln in self.lines if ln["mpn"] == "CL05B104KO5NNNC")
        self.assertEqual(target["quantity_per_board"], 21)
        self.assertEqual(len(target["references"]), 21)
        self.assertEqual(target["lcsc"], "C1525")

    def test_reference_ranges_expand(self):
        from provenmetal_kicad.grouping import _split_refs
        self.assertEqual(_split_refs("C2,C8,C11-C18"),
                         ["C2", "C8", "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C18"])
        self.assertEqual(_split_refs("D2-D8"), ["D2", "D3", "D4", "D5", "D6", "D7", "D8"])
        # A non-range token is passed through untouched.
        self.assertEqual(_split_refs("U1"), ["U1"])

    def test_line_key_precedence(self):
        self.assertEqual(line_key_for({"mpn": "ABC", "lcsc": "C1", "value": "10k"}), "abc")
        self.assertEqual(line_key_for({"mpn": "", "lcsc": "C1", "value": "10k"}), "c1")
        self.assertEqual(line_key_for({"mpn": "", "lcsc": "", "value": "10k"}), "10k")
        self.assertIsNone(line_key_for({"mpn": "", "lcsc": "", "value": ""}))


if __name__ == "__main__":
    unittest.main()
