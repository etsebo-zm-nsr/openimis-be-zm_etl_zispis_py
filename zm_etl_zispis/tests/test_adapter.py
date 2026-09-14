"""ZISPIS adapter tests."""
from django.test import TestCase

from api_etl.config import build_source_config
from zm_etl_zispis.adapter import ZispisAdapter
from zm_etl_zispis.apps import DEFAULT_CONFIG

class ResolveDobTestCase(TestCase):
    """dateOfBirth fallback, and the limits of it.

    ZISPIS asked that records with no usable date still be registered. yearOfBirth is
    the agreed fallback - but it is NOT an independent field: it equals
    year(dateOfBirth) on 99.6% of records, so where the date is corrupt the year carries
    the same corruption. These tests pin that a corrupt year is rejected rather than
    salvaged into something that looks reported.
    """

    def _adapter(self):
        return ZispisAdapter(build_source_config("zispis", DEFAULT_CONFIG))

    def test_reported_date_is_kept_and_labelled(self):
        dob, source = self._adapter().resolve_dob({"yearOfBirth": 1985}, "1985-03-12")
        self.assertEqual(dob, "1985-03-12")
        self.assertEqual(source, "reported")

    def test_missing_date_is_derived_mid_year(self):
        dob, source = self._adapter().resolve_dob({"yearOfBirth": 1985}, None)
        self.assertEqual(dob, "1985-07-01")
        self.assertEqual(source, "derived_from_year_of_birth")

    def test_corrupt_year_is_rejected_not_truncated(self):
        """Observed in live data: yearOfBirth 19895989. Taking the first four digits
        would invent a confident 1989."""
        dob, source = self._adapter().resolve_dob({"yearOfBirth": 19895989}, None)
        self.assertIsNone(dob)

    def test_implausible_year_is_rejected(self):
        for year in (6012, 2182, 6, 0):
            dob, _ = self._adapter().resolve_dob({"yearOfBirth": year}, None)
            self.assertIsNone(dob, f"yearOfBirth {year} should not produce a date")

    def test_absent_year_yields_nothing(self):
        dob, source = self._adapter().resolve_dob({}, None)
        self.assertIsNone(dob)
        self.assertEqual(source, "reported")

    def test_derived_dates_are_mid_year_not_january(self):
        """A 1 January cluster reads as fact and skews age-banded targeting."""
        dob, _ = self._adapter().resolve_dob({"yearOfBirth": 2000}, None)
        self.assertTrue(dob.endswith("-07-01"))
