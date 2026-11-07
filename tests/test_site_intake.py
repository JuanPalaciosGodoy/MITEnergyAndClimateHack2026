"""Offline checks for the conversions and evidence gaps used in the demo."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from API.green_button import read_green_button
from API.site_record import build_site_record


def sample_feed(multiplier=0, uom=72, accumulation=4, duration=900):
    """Two meters with different ReadingTypes catch accidental global-unit reuse."""
    return f'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:e="http://naesb.org/espi">
      <entry><link rel="self" href="https://example.org/MeterReading/1"/>
        <link rel="related" href="https://example.org/ReadingType/1"/>
        <content><e:MeterReading/></content></entry>
      <entry><link rel="self" href="https://example.org/ReadingType/1"/>
        <content><e:ReadingType><e:uom>{uom}</e:uom>
          <e:accumulationBehaviour>{accumulation}</e:accumulationBehaviour>
          <e:powerOfTenMultiplier>{multiplier}</e:powerOfTenMultiplier>
          <e:flowDirection>1</e:flowDirection><e:phase>769</e:phase>
        </e:ReadingType></content></entry>
      <entry><link rel="self" href="https://example.org/MeterReading/1/IntervalBlock/1"/>
        <content><e:IntervalBlock><e:IntervalReading>
          <e:timePeriod><e:start>0</e:start><e:duration>{duration}</e:duration></e:timePeriod>
          <e:value>250</e:value><e:ReadingQuality><e:quality>7</e:quality></e:ReadingQuality>
        </e:IntervalReading></e:IntervalBlock></content></entry>
      <entry><link rel="self" href="https://example.org/MeterReading/2"/>
        <link rel="related" href="https://example.org/ReadingType/2"/>
        <content><e:MeterReading/></content></entry>
      <entry><link rel="self" href="https://example.org/ReadingType/2"/>
        <content><e:ReadingType><e:uom>72</e:uom><e:accumulationBehaviour>4</e:accumulationBehaviour>
          <e:powerOfTenMultiplier>3</e:powerOfTenMultiplier><e:flowDirection>19</e:flowDirection>
        </e:ReadingType></content></entry>
      <entry><link rel="self" href="https://example.org/MeterReading/2/IntervalBlock/1"/>
        <content><e:IntervalBlock><e:IntervalReading>
          <e:timePeriod><e:start>0</e:start><e:duration>3600</e:duration></e:timePeriod>
          <e:value>2</e:value>
        </e:IntervalReading></e:IntervalBlock></content></entry>
    </feed>'''


class GreenButtonTests(unittest.TestCase):
    def parse(self, xml):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.xml"
            path.write_text(xml)
            return read_green_button(path)

    def test_units_separate_meters_and_utc(self):
        frame = self.parse(sample_feed())
        self.assertEqual(frame["energy_kwh"].to_list(), [0.25, 2.0])
        self.assertEqual(frame["average_kw"].to_list(), [1.0, 2.0])
        self.assertEqual(frame["interval_start_utc"][0], datetime(1970, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(frame["interval_end_utc"][0].minute, 15)
        self.assertEqual(frame["flow_direction"].to_list(), ["1", "19"])
        self.assertEqual(frame["reading_quality"][0], "7")
        self.assertEqual(frame["data_kind"][0], "customer_provided")
        self.assertEqual(len(frame["source_sha256"][0]), 64)

    def test_negative_multiplier(self):
        frame = self.parse(sample_feed(multiplier=-1))
        self.assertAlmostEqual(frame["energy_kwh"][0], 0.025)

    def test_unsupported_readings_fail(self):
        for kwargs in [{"uom": 38}, {"accumulation": 3}, {"duration": 0}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.parse(sample_feed(**kwargs))

    def test_missing_reading_type_fails(self):
        xml = sample_feed().replace('rel="related" href="https://example.org/ReadingType/1"',
                                    'rel="related" href="https://example.org/ReadingType/missing"')
        with self.assertRaisesRegex(ValueError, "ReadingType"):
            self.parse(xml)

    def test_empty_feed_fails(self):
        with self.assertRaisesRegex(ValueError, "No IntervalReading"):
            self.parse('<feed xmlns="http://www.w3.org/2005/Atom"/>')


class SiteRecordTests(unittest.TestCase):
    def test_missing_inputs_and_zero_preserved(self):
        record = build_site_record({
            "building_id": "123", "state": "MA", "data_year": 2025,
            "address": "Example St", "annual_electricity_kwh": 0,
            "source_url": "https://example.org/disclosure", "data_kind": "reported",
            "retrieved_at_utc": datetime(2026, 11, 7, tzinfo=timezone.utc),
        })
        self.assertEqual(record.height, record["field"].n_unique())
        known = record.filter(record["field"] == "annual_electricity_kwh").row(0, named=True)
        self.assertEqual(known["value"], "0")
        self.assertEqual(known["confidence"], "unreviewed")
        self.assertFalse(known["is_missing"])
        unknown = record.filter(record["field"] == "service_voltage_v").row(0, named=True)
        self.assertEqual(unknown["status"], "missing")
        self.assertIsNone(unknown["source_url"])
        self.assertTrue(unknown["input_to_request"])
        self.assertTrue(record["site_id"].eq("MA:123").all())


if __name__ == "__main__":
    unittest.main()
