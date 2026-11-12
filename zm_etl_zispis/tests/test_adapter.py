"""ZISPIS adapter tests."""
from django.test import TestCase

from api_etl.config import build_source_config
from zm_etl_zispis.adapter import ZispisAdapter
from zm_etl_zispis.apps import DEFAULT_CONFIG

def _adapter():
    return ZispisAdapter(build_source_config("zispis", DEFAULT_CONFIG))


def _row(**extra):
    row = {"firstName": "A", "lastName": "B", "gender": "MALE", "beneficiaryId": "x1"}
    row.update(extra)
    return row


class ResolveDobTestCase(TestCase):
    """The registry stores only the date of birth the source asserted.

    yearOfBirth and age used to be turned into an estimated dob. Neither is a date of
    birth, and a generated value in that field reads as fact downstream, so an unusable
    date now resolves to None.
    """

    def test_reported_date_is_kept(self):
        self.assertEqual(_adapter().resolve_dob(_row(dateOfBirth="1985-03-12")), "1985-03-12")

    def test_year_of_birth_does_not_produce_a_date(self):
        self.assertIsNone(_adapter().resolve_dob(_row(yearOfBirth=1985)))

    def test_age_does_not_produce_a_date(self):
        row = _row(age=9, createdAt="2021-11-20T20:34:13.000+0000")
        self.assertIsNone(_adapter().resolve_dob(row))

    def test_impossible_date_resolves_to_none(self):
        self.assertIsNone(_adapter().resolve_dob(_row(dateOfBirth="6012-06-04")))

    def test_absent_date_resolves_to_none(self):
        self.assertIsNone(_adapter().resolve_dob(_row()))


class NoInventedDobTestCase(TestCase):
    """transform_row keeps what was sent and generates nothing."""

    def test_unusable_dob_is_null_and_raw_value_kept(self):
        record = _adapter().transform_row(
            _row(dateOfBirth="6012-06-04", yearOfBirth=6012, age=9,
                 createdAt="2021-11-20T20:34:13.000+0000"))
        self.assertIsNone(record["dob"])
        self.assertEqual(record["dob_as_sent"], "6012-06-04")

    def test_unparseable_dob_is_kept_as_sent(self):
        record = _adapter().transform_row(_row(dateOfBirth="  not   a date "))
        self.assertIsNone(record["dob"])
        self.assertEqual(record["dob_as_sent"], "not a date")

    def test_valid_dob_has_no_dob_as_sent(self):
        record = _adapter().transform_row(_row(dateOfBirth="1985-03-12"))
        self.assertEqual(record["dob"], "1985-03-12")
        self.assertNotIn("dob_as_sent", record)

    def test_no_dob_sent_has_no_dob_as_sent(self):
        for extra in ({}, {"dateOfBirth": None}, {"dateOfBirth": ""}, {"dateOfBirth": "  "}):
            record = _adapter().transform_row(_row(**extra))
            self.assertIsNone(record["dob"], extra)
            self.assertNotIn("dob_as_sent", record, extra)

    def test_no_dob_and_no_age_is_still_emitted(self):
        adapter = _adapter()
        out = adapter.transform([_row()])
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0]["dob"])
        self.assertEqual(adapter.skipped, [])
        self.assertEqual(adapter.held_rows, [])
        self.assertEqual(adapter.missing_required(out[0]), [])

    def test_dob_is_not_required_by_the_zispis_config(self):
        required = build_source_config("zispis", DEFAULT_CONFIG).adapter.required_fields
        self.assertNotIn("dob", required)
        self.assertEqual(required, ["first_name", "last_name"])

    def test_age_and_registered_at_are_stored_as_sent(self):
        record = _adapter().transform_row(
            _row(age=9, createdAt="2021-11-20T20:34:13.000+0000"))
        self.assertEqual(record["age"], 9)
        self.assertEqual(record["registered_at"], "2021-11-20T20:34:13.000+0000")

    def test_age_is_not_turned_into_a_year_of_birth(self):
        record = _adapter().transform_row(
            _row(age=9, createdAt="2021-11-20T20:34:13.000+0000"))
        self.assertIsNone(record["year_of_birth"])

    def test_declared_extra_columns(self):
        extra = build_source_config("zispis", DEFAULT_CONFIG).adapter.extra_columns
        self.assertIn("dob_as_sent", extra)
        self.assertNotIn("dob_source", extra)


class CorruptYearOfBirthTestCase(TestCase):
    """A corrupt yearOfBirth must not reach the identity key."""

    def _transform(self, **extra):
        return _adapter().transform_row(
            _row(age=9, createdAt="2021-11-20T20:34:13.000+0000", **extra))

    def test_corrupt_year_cleared_when_dob_unusable(self):
        record = self._transform(dateOfBirth="6012-06-04", yearOfBirth=6012)
        self.assertIsNone(record["dob"])
        self.assertIsNone(record["year_of_birth"])

    def test_reported_year_is_kept(self):
        record = self._transform(dateOfBirth="1985-03-12", yearOfBirth=1985)
        self.assertEqual(record["year_of_birth"], 1985)

    def test_corrupt_year_cleared_even_when_dob_reported(self):
        record = self._transform(dateOfBirth="1985-03-12", yearOfBirth=19895989)
        self.assertEqual(record["dob"], "1985-03-12")
        self.assertIsNone(record["year_of_birth"])

    def test_corrupt_year_is_rejected_not_truncated(self):
        """Observed in live data: yearOfBirth 19895989. Taking the first four digits
        would invent a confident 1989."""
        for year in (19895989, 6012, 2182, 6, 0):
            record = self._transform(yearOfBirth=year)
            self.assertIsNone(record["year_of_birth"], year)


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
