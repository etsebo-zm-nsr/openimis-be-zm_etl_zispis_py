"""ZISPIS-specific transformation.

Everything expressible as configuration lives in `apps.py`. What remains here is the
handful of things ZISPIS does that config cannot describe: roles that need a second
field to disambiguate, and identity values the source deliberately poisons.
"""
import logging
from datetime import date, datetime, timedelta

from api_etl.adapters import BaseMappingAdapter

logger = logging.getLogger(__name__)

# ZISPIS collapses gendered relationships into one code; openIMIS keeps them apart.
# `gender` resolves them, and this covers 90% of the roster: SON_OR_DAUGHTER and
# GRANDCHILD alone are ~52% of all records.
GENDERED_ROLES = {
    "SON_OR_DAUGHTER":   {"MALE": "SON", "FEMALE": "DAUGHTER"},
    "GRANDCHILD":        {"MALE": "GRANDSON", "FEMALE": "GRANDDAUGHTER"},
    "BROTHER_OR_SISTER": {"MALE": "BROTHER", "FEMALE": "SISTER"},
    "FATHER_OR_MOTHER":  {"MALE": "FATHER", "FEMALE": "MOTHER"},
    "GRANDPARENT":       {"MALE": "GRANDFATHER", "FEMALE": "GRANDMOTHER"},
}

# ZISPIS marks its own known-duplicate identities inside the national ID field rather
# than in a flag: a "/DUPLICATE" suffix, and a 999999/99/* placeholder. Used as-is both
# become a match key shared by many unrelated people, which is precisely how a registry
# merges two different human beings.
DUPLICATE_SUFFIX = "/DUPLICATE"
PLACEHOLDER_ID_PREFIX = "999999"

# Where a record's date of birth came from. Written to every row, so "reported" is an
# assertion rather than merely the absence of a flag.
DOB_REPORTED = "reported"
DOB_DERIVED = "derived_from_year_of_birth"
DOB_ESTIMATED_FROM_AGE = "estimated_from_age_at_registration"
# Mid-year, so a derived date is on average closest to the truth and is visibly not a
# real birthday (a 1 January cluster reads as fact and skews age-banded targeting).
DERIVED_DOB_MONTH_DAY = "-07-01"


class ZispisAdapter(BaseMappingAdapter):

    def map_role(self, raw_role):
        """Resolve ZISPIS's gender-ambiguous roles, else fall back to the config map."""
        key = str(raw_role).strip().upper() if raw_role not in (None, "") else ""
        if key in GENDERED_ROLES:
            gender = str(self._current_gender or "").strip().upper()
            mapped = GENDERED_ROLES[key].get(gender)
            if mapped:
                return mapped
            # Gender absent or unexpected: a neutral relative is honest, an invented
            # SON-or-DAUGHTER guess is not.
            return self.cfg.adapter.default_role or "OTHER_RELATIVE"
        return super().map_role(raw_role)

    def map_recipient(self, value):
        """ZISPIS designates the recipient by role rather than a dedicated flag."""
        if str(value or "").strip().upper() == "HEAD":
            return "1"
        return None

    def clean_national_id(self, value):
        """Strip ZISPIS's duplicate markers; treat placeholders as no identity at all."""
        if value in (None, ""):
            return None, None
        text = str(value).strip()
        flagged = None
        if text.upper().endswith(DUPLICATE_SUFFIX):
            text = text[: -len(DUPLICATE_SUFFIX)].strip()
            flagged = "zispis marked this national id as a duplicate"
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits.startswith(PLACEHOLDER_ID_PREFIX):
            return None, "zispis placeholder national id (999999...) treated as absent"
        return (text or None), flagged

    def resolve_dob(self, row, mapped_dob):
        """Return (dob, provenance).

        ZISPIS confirmed that records with no usable date of birth must still be
        registered - historical data predating CORE MIS often lacks one - but
        `individual_individual.dob` is NOT NULL, so "no date" is not representable.

        MEASURED: `yearOfBirth` is NOT an independent field. It equals
        `year(dateOfBirth)` on 99.6% of 5,000 sampled records, and where the date is
        corrupt the year carries the same corruption (dateOfBirth `6012-06-04` has
        yearOfBirth 6012), so that fallback rescues 0% of the ~3% unusable dates.

        `age` does survive. It is the person's age at REGISTRATION (not today), so
        `createdAt.year - dob.year - age` is 0 or 1 for 96.8% of valid records, and it
        is present and in 0..120 for 3,471 of 3,482 unusable dates. The true birth date
        therefore lies in (createdAt - (age+1)y, createdAt - age y]; we take the
        midpoint. It is an estimate good to about +-6 months, and is labelled as one.

        Precedence: reported date, plausible yearOfBirth, age estimate, then nothing.

        The provenance column exists because a derived date must never be mistaken for a
        reported one: it is accurate to within a year, which is fine for age banding and
        wrong for anything that turns on an exact birthday.
        """
        if mapped_dob:
            return mapped_dob, DOB_REPORTED
        derived = self._dob_from_year(self.resolve_path(row, "yearOfBirth"))
        if derived:
            return derived, DOB_DERIVED
        estimated = self._dob_from_age(self.resolve_path(row, "age"),
                                       self.resolve_path(row, "createdAt"))
        if estimated:
            return estimated, DOB_ESTIMATED_FROM_AGE
        return None, DOB_REPORTED

    def _dob_from_year(self, year):
        try:
            # The WHOLE value must be a plausible year. Taking the first four digits
            # would turn the observed yearOfBirth 19895989 into a confident-looking
            # 1989 - a birth year invented by truncation, indistinguishable downstream
            # from one the source actually reported.
            year = int(str(year).strip())
        except (TypeError, ValueError):
            return None
        # Fails the same plausibility window as any other date - a yearOfBirth of
        # 0002 is no more usable than a dateOfBirth of 0002.
        return self.parse_date(f"{year}{DERIVED_DOB_MONTH_DAY}")

    def _dob_from_age(self, age, created_at):
        """Midpoint of the birth-date window implied by age at registration."""
        try:
            if isinstance(age, float):
                if age != int(age):
                    return None
            age = int(str(int(age)) if isinstance(age, float) else str(age).strip())
            registered = datetime.strptime(str(created_at).strip()[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError, OverflowError):
            return None
        if not 0 <= age <= 120:
            return None
        year = registered.year - age
        if year < 1:
            return None
        try:
            anniversary = registered.replace(year=year)
        except ValueError:  # 29 February, target year not leap
            anniversary = date(year, 2, 28)
        # Half a year before the age-th birthday window closes; never after registration.
        midpoint = anniversary - timedelta(days=182)
        return self.parse_date(midpoint.strftime("%Y-%m-%d"))

    def transform_row(self, row):
        # map_role needs gender, which the base class does not pass down. Held per row
        # rather than threaded through the signature so the core SPI stays unchanged.
        self._current_gender = self.resolve_path(row, "gender")
        try:
            record = super().transform_row(row)
        finally:
            self._current_gender = None
        if record is None:
            return None

        record["dob"], record["dob_source"] = self.resolve_dob(row, record.get("dob"))
        if record["dob_source"] != DOB_REPORTED or not record["dob"]:
            # year_of_birth feeds the identity key. Where the date was not reported the
            # year is usually the same corruption (6012), so keep it only if plausible.
            # An age-based estimate is +-1 year and is deliberately not written here.
            if not self._plausible_year(record.get("year_of_birth")):
                record["year_of_birth"] = None

        national_id, note = self.clean_national_id(self.resolve_path(row, "nationalId"))
        record["national_id"] = self.normalise_national_id(national_id)
        if note:
            # Surfaced rather than silently dropped: a person whose only identifier is
            # unusable still belongs in the registry, flagged for a caseworker.
            #
            # Deliberately NOT `linkage_note`: the sink writes that key for its own
            # identity decisions, and it would overwrite this one - losing exactly the
            # explanation the checker needs. A placeholder national id is *why* an id
            # matches two hundred people, so the two notes have to survive together.
            record["data_quality_note"] = note

        return record

    def _plausible_year(self, value):
        try:
            year = int(str(value).strip())
        except (TypeError, ValueError):
            return False
        adapter = self.cfg.adapter
        return (adapter.min_year or 0) <= year <= (adapter.max_year or datetime.now().year)

    _current_gender = None
