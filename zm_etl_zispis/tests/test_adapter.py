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


class AgeEstimateDobTestCase(TestCase):
    """Fallback to age at registration when the reported date and year are unusable."""

    def _adapter(self):
        return ZispisAdapter(build_source_config("zispis", DEFAULT_CONFIG))

    def _dob(self, row, mapped=None):
        return self._adapter().resolve_dob(row, mapped)

    def test_estimate_is_midpoint_of_window(self):
        row = {"yearOfBirth": 6012, "age": 9, "createdAt": "2021-11-20T20:34:13.000+0000"}
        self.assertEqual(self._dob(row), ("2012-05-22", "estimated_from_age_at_registration"))

    def test_z_suffix_and_string_age(self):
        row = {"age": "9", "createdAt": "2021-11-20T20:34:13Z"}
        self.assertEqual(self._dob(row)[0], "2012-05-22")

    def test_leap_day_registration(self):
        row = {"age": 9, "createdAt": "2020-02-29T00:00:00.000+0000"}
        # 2011 is not leap: 2011-02-28 minus 182 days
        self.assertEqual(self._dob(row)[0], "2010-08-30")

    def test_age_zero(self):
        row = {"age": 0, "createdAt": "2021-11-20T00:00:00.000+0000"}
        dob, source = self._dob(row)
        self.assertEqual(dob, "2021-05-22")
        self.assertEqual(source, "estimated_from_age_at_registration")

    def test_age_out_of_range_gives_nothing(self):
        for age in (121, -1, 999, "abc", 4.5, None):
            dob, source = self._dob({"age": age, "createdAt": "2021-11-20T00:00:00.000+0000"})
            self.assertIsNone(dob, f"age {age!r}")
            self.assertEqual(source, "reported")

    def test_missing_or_bad_created_at_gives_nothing(self):
        self.assertIsNone(self._dob({"age": 9})[0])
        self.assertIsNone(self._dob({"age": 9, "createdAt": "garbage"})[0])

    def test_implausible_estimate_gives_nothing(self):
        # 1900 minimum year: registered 2000, age 120 -> 1880
        self.assertIsNone(self._dob({"age": 120, "createdAt": "2000-01-01T00:00:00Z"})[0])

    def test_reported_date_wins(self):
        row = {"age": 9, "createdAt": "2021-11-20T00:00:00.000+0000", "yearOfBirth": 1985}
        self.assertEqual(self._dob(row, "1985-03-12"), ("1985-03-12", "reported"))

    def test_plausible_year_wins_over_age(self):
        row = {"age": 9, "createdAt": "2021-11-20T00:00:00.000+0000", "yearOfBirth": 1985}
        self.assertEqual(self._dob(row), ("1985-07-01", "derived_from_year_of_birth"))


class CorruptYearOfBirthTestCase(TestCase):
    """A corrupt yearOfBirth must not reach the identity key."""

    def _transform(self, **extra):
        adapter = ZispisAdapter(build_source_config("zispis", DEFAULT_CONFIG))
        row = {"firstName": "A", "lastName": "B", "gender": "MALE", "beneficiaryId": "x1",
               "age": 9, "createdAt": "2021-11-20T20:34:13.000+0000"}
        row.update(extra)
        return adapter.transform_row(row)

    def test_corrupt_year_cleared_when_dob_estimated(self):
        record = self._transform(dateOfBirth="6012-06-04", yearOfBirth=6012)
        self.assertEqual(record["dob"], "2012-05-22")
        self.assertEqual(record["dob_source"], "estimated_from_age_at_registration")
        self.assertIsNone(record["year_of_birth"])

    def test_reported_year_is_kept(self):
        record = self._transform(dateOfBirth="1985-03-12", yearOfBirth=1985)
        self.assertEqual(record["dob_source"], "reported")
        self.assertEqual(record["year_of_birth"], 1985)


class RoleMapTestCase(TestCase):
    """DEFAULT_CONFIG.adapter.role_map coverage for raw ZISPIS roles.

    Measured against the live pull: UNCLE_OR_AUNT (295), FATHER_IN_LAW_OR_MOTHER_IN_LAW
    (115), NIECE (6) and HUSBAND (1) were all silently falling through to
    adapter.default_role, unmapped.
    """

    def _adapter(self):
        return ZispisAdapter(build_source_config("zispis", DEFAULT_CONFIG))

    def test_husband_maps_to_spouse(self):
        self.assertEqual(self._adapter().map_role("HUSBAND"), "SPOUSE")
