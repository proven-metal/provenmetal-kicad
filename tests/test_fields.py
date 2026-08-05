import unittest

from _bootstrap import *  # noqa: F401,F403 (sys.path bootstrap)

from provenmetal_kicad import fields


class TestFieldSpec(unittest.TestCase):
    def test_fields_and_labels_align(self):
        fields_arg, labels_arg, group_by = fields.build_field_spec()
        self.assertEqual(len(fields_arg.split(",")), len(labels_arg.split(",")))
        # Generated fields are requested for qty/dnp.
        self.assertIn("${QUANTITY}", fields_arg)
        self.assertIn("${DNP}", fields_arg)
        # First label of each canonical is the bare canonical name.
        self.assertIn("mpn", labels_arg.split(","))
        self.assertIn("lcsc", labels_arg.split(","))
        # group-by is limited to real (non-generated) fields.
        self.assertIn("Value", group_by)
        self.assertIn("Footprint", group_by)
        self.assertNotIn("${", group_by)

    def test_pinned_field_map_is_tried_first(self):
        fields_arg, labels_arg, _ = fields.build_field_spec({"mpn": "My Part Number"})
        cols = fields_arg.split(",")
        labels = labels_arg.split(",")
        # The pinned name should appear, and be the first mpn-labelled column.
        self.assertIn("My Part Number", cols)
        mpn_index = labels.index("mpn")
        self.assertEqual(cols[mpn_index], "My Part Number")


class TestCoalesce(unittest.TestCase):
    def test_coalesces_secondary_variants(self):
        raw = {"mpn": "", "mpn__1": "STM32", "lcsc": "", "lcsc__1": "C123", "value": "MCU"}
        out = fields.coalesce_row(raw)
        self.assertEqual(out["mpn"], "STM32")
        self.assertEqual(out["lcsc"], "C123")
        self.assertEqual(out["value"], "MCU")

    def test_prefers_primary_when_present(self):
        raw = {"mpn": "PRIMARY", "mpn__1": "secondary"}
        out = fields.coalesce_row(raw)
        self.assertEqual(out["mpn"], "PRIMARY")

    def test_missing_columns_default_empty(self):
        out = fields.coalesce_row({"value": "10k"})
        self.assertEqual(out["mpn"], "")
        self.assertEqual(out["value"], "10k")


if __name__ == "__main__":
    unittest.main()
