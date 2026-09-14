"""ZISPIS-specific transformation.

Everything expressible as configuration lives in `apps.py`. What remains here is the
handful of things ZISPIS does that config cannot describe: roles that need a second
field to disambiguate, and identity values the source deliberately poisons.
"""
import logging

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

        MEASURED, and it is not what it looks like: `yearOfBirth` is NOT an independent
        field. It equals `year(dateOfBirth)` on 99.6% of 5,000 sampled records, and
        where the date is corrupt the year carries the same corruption - dateOfBirth
        `6012-06-04` has yearOfBirth 6012, `0006-07-08` has 6, and one record has
        19895989. So on current ZISPIS data this fallback rescues **0%** of the 3% of
        records whose date is unusable; they still cannot be represented.

        The path is kept because it is what was agreed and it costs nothing: if ZISPIS
        populates yearOfBirth independently, or another source does, it works. It is not
        a solution to the 3% today - see the ZISPIS doc for the open decision.

        The provenance column exists because a derived date must never be mistaken for a
        reported one: it is accurate to within a year, which is fine for age banding and
        wrong for anything that turns on an exact birthday.
        """
        if mapped_dob:
            return mapped_dob, DOB_REPORTED
        year = self.resolve_path(row, "yearOfBirth")
        try:
            # The WHOLE value must be a plausible year. Taking the first four digits
            # would turn the observed yearOfBirth 19895989 into a confident-looking
            # 1989 - a birth year invented by truncation, indistinguishable downstream
            # from one the source actually reported.
            year = int(str(year).strip())
        except (TypeError, ValueError):
            return None, DOB_REPORTED
        derived = self.parse_date(f"{year}{DERIVED_DOB_MONTH_DAY}")
        if not derived:
            # Fails the same plausibility window as any other date - a yearOfBirth of
            # 0002 is no more usable than a dateOfBirth of 0002.
            return None, DOB_REPORTED
        return derived, DOB_DERIVED

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

    _current_gender = None
