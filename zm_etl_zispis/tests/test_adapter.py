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


class LocationCodeTestCase(TestCase):
    """The village code is `district/ward`, and constituency is deliberately excluded.

    openIMIS resolves a village by joining tblLocations on name AND code with
    LocationType='V'. Ward names repeat across districts (MULULU in both MAFINGA and
    NSAMA), so a bare name as the code matches two rows and the LEFT JOIN inserts the
    individual twice.

    Constituency is the ward's parent tier but must not be in its identity: 52
    (district, ward) pairs resolve to more than one constituency, so including it would
    give one real ward two codes and split it into two Location rows.
    """

    def _adapter(self):
        return ZispisAdapter(build_source_config("zispis", DEFAULT_CONFIG))

    @staticmethod
    def _row(district, ward, constituency="SOME CONSTITUENCY"):
        return {"location": {"province": "SOUTHERN", "district": district,
                             "constituency": constituency, "ward": ward}}

    def test_code_is_district_and_ward(self):
        self.assertEqual(
            self._adapter().location_code(self._row("SINAZONGWE", "MALIMA")),
            "SINAZONGWE/MALIMA")

    def test_same_ward_name_in_two_districts_gets_different_codes(self):
        a = self._adapter()
        self.assertNotEqual(a.location_code(self._row("MAFINGA", "MULULU")),
                            a.location_code(self._row("NSAMA", "MULULU")))

    def test_constituency_does_not_change_the_code(self):
        """The property that stops one ward becoming two villages."""
        a = self._adapter()
        self.assertEqual(
            a.location_code(self._row("MASAITI", "SHIMIBANGA", "MASAITI")),
            a.location_code(self._row("MASAITI", "SHIMIBANGA", "MASAITI CENTRAL")))

    def test_whitespace_variants_collapse_to_one_code(self):
        a = self._adapter()
        self.assertEqual(a.location_code(self._row("SINAZONGWE", "MALIMA")),
                         a.location_code(self._row(" SINAZONGWE ", "MALIMA\n")))

    def test_overlong_code_is_digest_suffixed_not_merely_truncated(self):
        a = self._adapter()
        long_a = a.location_code(self._row("D" * 40, "W" * 40))
        long_b = a.location_code(self._row("D" * 40, "W" * 39 + "X"))
        self.assertLessEqual(len(long_a), 50)
        self.assertNotEqual(long_a, long_b, "truncation alone would collide")

    def test_missing_geography_yields_no_code(self):
        self.assertIsNone(self._adapter().location_code({"location": {}}))
