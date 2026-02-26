"""
rainfall_data.py
----------------
Provides the RainfallData class for fetching, parsing, and cleaning
intensity-duration-frequency (IDF) rainfall data from NOAA or arbitrary
text strings.  Designed for use in a Flask application — all public methods
return structured results and raise RainfallDataError on failure so callers
can translate errors into HTTP responses cleanly.
"""

import re
import requests
from collections import defaultdict


# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------

class RainfallDataError(Exception):
    """Base exception for all RainfallData errors.

    Attributes
    ----------
    message : str
        Human-readable description of the error.
    status_code : int
        Suggested HTTP status code for Flask error handlers (default 400).
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict suitable for a Flask error response."""
        return {"error": self.__class__.__name__, "message": self.message}


class RainfallFetchError(RainfallDataError):
    """Raised when the NOAA HTTP request fails."""

    def __init__(self, message: str):
        super().__init__(message, status_code=502)


class RainfallParseError(RainfallDataError):
    """Raised when the data cannot be parsed into a usable structure."""

    def __init__(self, message: str):
        super().__init__(message, status_code=422)


class RainfallValidationError(RainfallDataError):
    """Raised when the parsed data dict fails internal consistency checks."""

    def __init__(self, message: str):
        super().__init__(message, status_code=422)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class RainfallData:
    """Parse and clean intensity-duration-frequency (IDF) rainfall data.

    Data can be loaded from:
    * NOAA's HDSC web service via :meth:`get_from_noaa`.
    * An arbitrary formatted text string via :meth:`clean_arbitrary_data`.

    After a successful load the cleaned data is stored in :attr:`data` as::

        {return_period_years: {duration_minutes: intensity_in_per_hr, ...}, ...}

    Attributes
    ----------
    data : dict or None
        Parsed IDF data keyed by return-period year then duration in minutes.
    lat : float or None
        Latitude used for the most recent NOAA fetch.
    lon : float or None
        Longitude used for the most recent NOAA fetch.
    years : list[int] or None
        Return-period years found in the most recently parsed dataset.
    """

    def __init__(self):
        self.data = None
        self.lat: float | None = None
        self.lon: float | None = None
        self.years: list[int] | None = None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_dict(self) -> bool:
        """Check that :attr:`data` is internally consistent.

        Returns
        -------
        bool
            ``True`` if the data dict passes all consistency checks.

        Raises
        ------
        RainfallValidationError
            If the data dict is ``None`` or fails a consistency check.
        """
        if self.data is None:
            raise RainfallValidationError("No data loaded — call get_from_noaa or clean_arbitrary_data first.")

        try:
            year_keys = sorted(self.data.keys())

            if self.years is not None:
                expected = sorted(self.years)
                if year_keys != expected:
                    raise RainfallValidationError(
                        f"Data keys {year_keys} do not match expected years {expected}."
                    )

            duration_sets = [frozenset(self.data[y].keys()) for y in year_keys]
            if len(set(duration_sets)) > 1:
                raise RainfallValidationError(
                    "Duration keys are not identical across all return periods."
                )

            return True

        except RainfallValidationError:
            raise
        except Exception as exc:
            raise RainfallValidationError(f"Unexpected validation error: {exc}") from exc

    # ------------------------------------------------------------------
    # Line filtering helpers
    # ------------------------------------------------------------------

    def _filter_lines(
        self,
        lines: list[str],
        exclude_chars: list[str] | None = None,
        whitelist: list[str] | str | None = None,
        num_unique_letters: int = 10,
    ) -> list[str]:
        """Filter raw text lines, keeping only those likely to contain data.

        Lines are kept if they:
        * Contain any string from *whitelist*, OR
        * Have fewer than *num_unique_letters* distinct alphabetic characters
          AND do not contain any character in *exclude_chars*.

        Parameters
        ----------
        lines : list[str]
            Raw lines from the source text.
        exclude_chars : list[str] or None
            Characters that disqualify a line (e.g. ``['#', '!']``).
        whitelist : list[str] or str or None
            Substrings that force a line to be kept regardless of other rules.
        num_unique_letters : int
            Maximum number of unique letters a line may contain and still be
            kept (used to reject prose header lines).

        Returns
        -------
        list[str]
            Filtered subset of *lines*.
        """
        if whitelist and not isinstance(whitelist, list):
            whitelist = [whitelist]
        result = []
        for line in lines:
            unique_letters = {c.lower() for c in line if c.isalpha()}
            if whitelist and any(x in line for x in whitelist):
                result.append(line)
            elif len(unique_letters) >= num_unique_letters:
                continue
            elif exclude_chars and any(x in line for x in exclude_chars):
                continue
            else:
                result.append(line)
        return result

    # ------------------------------------------------------------------
    # Duration helpers
    # ------------------------------------------------------------------

    def _duration_match(self, line: str) -> tuple[int | None, int | None]:
        """Extract a duration value in minutes from a text line.

        Recognises patterns like ``"30 min"``, ``"2-hour"``, ``"1 day"``, etc.

        Parameters
        ----------
        line : str
            A single line of text to search.

        Returns
        -------
        duration_minutes : int or None
            The duration converted to minutes, or ``None`` if not found.
        duration_num : int or None
            The raw numeric part of the duration, or ``None`` if not found.
        """
        match = re.search(
            r'(\d+)\s*-?\s*(m|min|minute|minutes|h|hr|hour|hours|d|day|days)\b',
            line,
            re.IGNORECASE,
        )
        if match:
            duration_num = int(match.group(1))
            unit = match.group(2).lower()
            duration_minutes = self._convert_duration_to_minutes(duration_num, unit)
            return duration_minutes, duration_num
        return None, None

    def _convert_duration_to_minutes(self, duration_num: int, unit: str) -> int | None:
        """Convert a duration number and unit string to minutes.

        Parameters
        ----------
        duration_num : int
            The numeric magnitude of the duration.
        unit : str
            One of ``m / min / minute / minutes``, ``h / hr / hour / hours``,
            or ``d / day / days``.

        Returns
        -------
        int or None
            Duration in minutes, or ``None`` if *unit* is unrecognised.
        """
        unit = unit.lower()
        if unit in ('m', 'min', 'minute', 'minutes'):
            return duration_num
        if unit in ('h', 'hr', 'hour', 'hours'):
            return duration_num * 60
        if unit in ('d', 'day', 'days'):
            return duration_num * 24 * 60
        return None

    # ------------------------------------------------------------------
    # Year-header detection
    # ------------------------------------------------------------------

    def _find_year_header(self, filtered_lines: list[str]) -> tuple[int, list[int]]:
        """Locate the line that lists return-period years and return its index.

        Searches for lines that contain two or more ``yr`` / ``year`` tokens, or
        that contain combinations of common return periods (2, 10, 100, etc.).

        Parameters
        ----------
        filtered_lines : list[str]
            Pre-filtered lines from the source text.

        Returns
        -------
        index : int
            Index of the year-header line within *filtered_lines*.
        years : list[int]
            Return-period years extracted from that line.

        Raises
        ------
        RainfallParseError
            If no suitable year-header line can be found.
        """
        for i, line in enumerate(filtered_lines):
            yr_count = len(re.findall(r'\b(yr|year)s?\b', line, re.IGNORECASE))
            if yr_count >= 2:
                result = [int(x) for x in re.findall(r'\b\d+\b', line)]
                if result:
                    self.years = result
                    return i, result
            numbers = [int(x) for x in re.findall(r'\b\d+\b', line)]
            if (2 in numbers and 10 in numbers and 100 in numbers) or \
                    (10 in numbers and 100 in numbers and 500 in numbers):
                self.years = numbers
                return i, numbers
        raise RainfallParseError("Could not find a return-period year header line in the data.")

    # ------------------------------------------------------------------
    # NOAA fetch
    # ------------------------------------------------------------------

    def get_link(self, lat: float, lon: float, reversed: bool = False) -> str | None:
        """Build the NOAA HDSC CSV download URL for a given location.

        Parameters
        ----------
        lat : float
            Latitude in decimal degrees.
        lon : float
            Longitude in decimal degrees.
        reversed : bool
            If ``True``, swap lat and lon in the URL (some NOAA endpoints
            expect lon first).

        Returns
        -------
        str or None
            The fully-formed URL, or ``None`` if *lat* / *lon* are not floats.
        """
        if isinstance(lat, float) and isinstance(lon, float):
            if reversed:
                lat_str = str(round(lon, 4))
                lon_str = str(round(lat, 4))
            else:
                lat_str = str(round(lat, 4))
                lon_str = str(round(lon, 4))
            return (
                f"https://hdsc.nws.noaa.gov/cgi-bin/hdsc/new/fe_text_mean.csv"
                f"?lat={lat_str}&lon={lon_str}&data=depth&units=english&series=pds"
            )
        return None

    def get_from_noaa(self, lat: float, lon: float, reversed: bool = False) -> bool:
        """Fetch and parse IDF data from the NOAA HDSC web service.

        Parameters
        ----------
        lat : float
            Latitude in decimal degrees.
        lon : float
            Longitude in decimal degrees.
        reversed : bool
            Pass ``True`` if the NOAA endpoint expects ``(lon, lat)`` order.

        Returns
        -------
        bool
            ``True`` if data was fetched and validated successfully.

        Raises
        ------
        RainfallFetchError
            If the HTTP request fails.
        RainfallParseError
            If the response cannot be parsed.
        RainfallValidationError
            If the parsed data fails consistency checks.
        """
        if reversed:
            self.lat, self.lon = lon, lat
        else:
            self.lat, self.lon = lat, lon

        link = self.get_link(lat, lon, reversed=False)
        if link is None:
            raise RainfallFetchError("lat and lon must both be floats to build a NOAA URL.")

        self.data = self._open_noaa_rainfall_csv(link)
        return self._validate_dict()

    def _open_noaa_rainfall_csv(self, link: str, convert_to_intensity: bool = True) -> dict:
        """Download and parse a NOAA HDSC CSV into the standard data dict.

        Parameters
        ----------
        link : str
            Full NOAA CSV URL.
        convert_to_intensity : bool
            If ``True`` (default) convert depth values to in/hr intensity.

        Returns
        -------
        dict
            ``{return_period_yr: {duration_min: value, ...}, ...}``

        Raises
        ------
        RainfallFetchError
            If the HTTP request fails.
        RainfallParseError
            If the response cannot be parsed.
        """
        if not isinstance(link, str):
            raise RainfallFetchError("Link must be a string.")

        try:
            response = requests.get(link, timeout=15)
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise RainfallFetchError(f"NOAA request returned HTTP error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise RainfallFetchError(f"NOAA request failed: {exc}") from exc

        rows = [line for line in response.text.splitlines() if line.strip()]
        filtered_lines = self._filter_lines(rows, whitelist="years", num_unique_letters=5)

        year_line_index, year_values = self._find_year_header(filtered_lines)

        data_dict: dict = {year: {} for year in year_values}

        for line in filtered_lines[year_line_index + 1:]:
            line = line.strip()
            if not line:
                continue

            duration_minutes, duration_num = self._duration_match(line)
            if duration_minutes is None:
                continue

            # Extract all numeric values; remove the duration number itself
            rainfall_values = [
                float(x)
                for x in re.findall(r'\d+\.\d+|\d+', line)
                if float(x) != duration_num
            ]

            if len(rainfall_values) == len(year_values):
                for year, value in zip(year_values, rainfall_values):
                    if convert_to_intensity:
                        data_dict[year][duration_minutes] = value / (duration_minutes / 60)
                    else:
                        data_dict[year][duration_minutes] = value

        if not any(data_dict[y] for y in data_dict):
            raise RainfallParseError("NOAA response was parsed but no data rows were extracted.")

        return data_dict

    # ------------------------------------------------------------------
    # Arbitrary string inspection
    # ------------------------------------------------------------------

    def arbitrary_data_info(
        self, rainfall_data: str, unique_only: bool = True
    ) -> tuple[list[dict], dict]:
        """Analyse an arbitrary rainfall data string line-by-line.

        For each non-empty line the method extracts counts and values for
        durations, return-period years, lone integers, lone decimals, ranges,
        percentage values, and in/hr unit labels.

        Parameters
        ----------
        rainfall_data : str
            Raw multi-line string containing IDF data in any recognisable format.
        unique_only : bool
            If ``True``, aggregate value lists contain only unique entries.

        Returns
        -------
        inspection : list[dict]
            Per-line analysis dicts with keys ``line``, ``counts``, ``values``.
        totals : dict
            Aggregated ``counts`` and ``values`` across all lines.
        """
        lines = rainfall_data.strip().split('\n')
        inspection_dict: list[dict] = []

        totals: dict = defaultdict(int)
        total_values: dict = defaultdict(list)

        def to_ints(lst):
            return [int(x) for x in lst]

        def to_floats(lst):
            return [float(x) for x in lst]

        for line in lines:
            line = line.strip()
            if not line:
                continue

            inches_per_hour = re.findall(
                r'\b(inches|in)\s*(/|-|per|p)\s*(hour|hr)\b', line, re.IGNORECASE
            )
            cleaned_line = re.sub(
                r'\b(inches|in)\s*(/|-|per|p)\s*(hour|hr)\b', '', line, flags=re.IGNORECASE
            )

            duration_matches = [
                (int(num) if num else None, unit)
                for num, unit in re.findall(
                    r'(\d+)?\s*-?\s*\b(m|min|minute|minutes|h|hr|hour|hours|d|day|days)\b',
                    cleaned_line,
                    re.IGNORECASE,
                )
            ]

            lone_ints = re.findall(r'(?:^|(?<=\s))(\d+)(?=\s|$)', line)
            lone_ints = [n for n in lone_ints if not re.search(rf'{n}\s+[a-zA-Z]', line)]

            lone_decimals = re.findall(r'(?:^|(?<=\s))(\d+\.\d+)(?=\s|$)', line)
            lone_decimals = [n for n in lone_decimals if not re.search(rf'{n}\s+[a-zA-Z]', line)]

            ranges = re.findall(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)', line)

            year_matches = [
                (int(num) if num else None, unit)
                for num, unit in re.findall(
                    r'(\d+)?\s*-?\s*\b(yr|year)s?\b', line, re.IGNORECASE
                )
            ]

            percent_values = re.findall(r'(\d+\.?\d*)%', line)

            counts = {
                'unique_letters_count': len({c.lower() for c in line if c.isalpha()}),
                'time_units_count': len(duration_matches),
                'time_values_count': sum(1 for num, _ in duration_matches if num is not None),
                'lone_decimals_count': len(lone_decimals),
                'lone_ints_count': len(lone_ints),
                'ranges_count': len(ranges),
                'year_label_count': sum(1 for _, label in year_matches if label is not None),
                'percent_values_count': len(percent_values),
                'inches_per_hour_label_count': len(inches_per_hour),
            }

            values = {
                'unique_letters': sorted({c.lower() for c in line if c.isalpha()}),
                'duration_matches': duration_matches,
                'lone_decimals': to_floats(lone_decimals),
                'lone_ints': to_ints(lone_ints),
                'ranges': [(float(a), float(b)) for a, b in ranges],
                'years': year_matches,
                'percent_values': to_floats(percent_values),
                'inches_per_hour': inches_per_hour,
            }

            inspection_dict.append({'line': line, 'counts': counts, 'values': values})

            for key, val in counts.items():
                if key != 'unique_letters_count':
                    totals[key] += val

            for key, vals in [
                ('duration_matches', duration_matches),
                ('lone_decimals', to_floats(lone_decimals)),
                ('lone_ints', to_ints(lone_ints)),
                ('ranges', [(float(a), float(b)) for a, b in ranges]),
                ('years', year_matches),
                ('percent_values', to_floats(percent_values)),
                ('inches_per_hour', re.findall(
                    r'\b(inches|in)\s*(/|-|per|p)\s*(hour|hr)\b', line, re.IGNORECASE
                )),
            ]:
                if unique_only:
                    total_values[key].extend(v for v in vals if v not in total_values[key])
                else:
                    total_values[key].extend(vals)

            letter_counts = [
                v['counts']['unique_letters_count']
                for v in inspection_dict
                if v['counts']['unique_letters_count'] > 0
            ]
            if letter_counts:
                totals['max_unique_letters'] = max(letter_counts)
                totals['min_unique_letters'] = min(letter_counts)

        return inspection_dict, {
            'counts': dict(totals),
            'values': dict(total_values),
        }

    # ------------------------------------------------------------------
    # Arbitrary string cleaning
    # ------------------------------------------------------------------

    def clean_arbitrary_data(
        self, rainfall_data: str, convert_to_intensity: bool = True
    ) -> dict:
        """Parse an arbitrary IDF data string into the standard data dict.

        The method inspects the string to detect one of three common layouts:

        **Layout A — years as labels, durations on each row**
            Each data row contains a duration token (e.g. ``30 min``) and one
            decimal value per return-period year.  Return-period years appear
            as labels (``yr`` / ``year``) rather than bare integers.

        **Layout B — years as bare integers, durations on each row**
            Similar to A but return-period years appear as lone integers on a
            header row.  Each subsequent row has a duration token and one value
            per year.  Handles the edge-case where each row carries only a
            single decimal value that accumulates until a full year-set is
            collected.

        **Layout C — durations as bare integers, years as labels**
            Lone integers are duration values sharing a single unit label.
            Return-period years appear as ``yr`` / ``year`` labels.  Each data
            row is expected to contain one decimal value per return-period year.

        The detected layout is logged via ``print`` for debugging; a
        :class:`RainfallParseError` is raised if no layout matches.

        .. note::
            ``duration_minutes`` is carried forward between rows so that
            formats where each line contains only one value (one per return
            period) still work correctly.

        Parameters
        ----------
        rainfall_data : str
            Multi-line string containing IDF data in any recognisable format.
        convert_to_intensity : bool
            If ``True`` (default), depth values (inches) are divided by the
            duration in hours to yield intensity (in/hr).

        Returns
        -------
        dict
            ``{return_period_yr: {duration_min: value, ...}, ...}``

        Raises
        ------
        RainfallParseError
            If the layout cannot be determined or no data rows are extracted.
        """
        inspection, totals = self.arbitrary_data_info(rainfall_data, unique_only=False)

        total_values = totals['values']
        total_counts = totals['counts']

        data_dict: dict | None = None

        # ------------------------------------------------------------------
        # Layout A: years are labels (yr/year tokens), durations on each row
        # ------------------------------------------------------------------
        if (
            total_counts.get('lone_ints_count', 0) == 0
            and total_counts.get('time_values_count', 0) > 0
            and total_counts.get('year_label_count', 0) > 0
        ):
            print("Layout A detected: year labels, duration on each row.")
            year_values = sorted(year for year, _ in total_values.get('years', []))
            if not year_values:
                raise RainfallParseError("Layout A: no year values could be extracted.")

            self.years = year_values
            data_dict = {year: {} for year in year_values}
            duration_minutes: int | None = None  # carry-forward across rows

            for row in inspection:
                counts = row['counts']
                values = row['values']

                if counts['time_values_count'] == 1 and values['duration_matches']:
                    dm = values['duration_matches'][0]
                    if dm[0] is not None:
                        duration_minutes = self._convert_duration_to_minutes(dm[0], dm[1])

                if duration_minutes is None:
                    continue

                is_increasing = all(
                    x < y for x, y in zip(values['lone_decimals'], values['lone_decimals'][1:])
                )
                if is_increasing and len(values['lone_decimals']) == len(year_values):
                    for i, year in enumerate(year_values):
                        if convert_to_intensity:
                            data_dict[year][duration_minutes] = (
                                values['lone_decimals'][i] / (duration_minutes / 60)
                            )
                        else:
                            data_dict[year][duration_minutes] = values['lone_decimals'][i]

        # ------------------------------------------------------------------
        # Layout B: years are lone ints, durations on each row
        # ------------------------------------------------------------------
        elif (
            total_counts.get('lone_decimals_count', 0) > 0
            and total_counts.get('time_units_count', 0) > 0
            and total_counts.get('lone_ints_count', 0) > 0
            and total_counts['lone_decimals_count'] // total_counts['time_units_count']
                == total_counts['lone_ints_count']
        ):
            print("Layout B detected: lone ints are years, durations on each row.")
            year_values = sorted(total_values.get('lone_ints', []))
            if not year_values:
                raise RainfallParseError("Layout B: no year values could be extracted from lone ints.")

            self.years = year_values
            data_dict = {year: {} for year in year_values}
            duration_minutes = None  # carry-forward
            pending_values: list[float] = []  # accumulates single-value rows

            for row in inspection:
                counts = row['counts']
                values = row['values']

                # Update duration if this row carries one
                if len(values['duration_matches']) == 1 and values['duration_matches'][0][0] is not None:
                    dm = values['duration_matches'][0]
                    new_duration = self._convert_duration_to_minutes(dm[0], dm[1])
                    # If we already accumulated values for the *previous* duration, flush them
                    if new_duration != duration_minutes and pending_values and duration_minutes is not None:
                        if len(pending_values) == len(year_values):
                            for i, year in enumerate(year_values):
                                if convert_to_intensity:
                                    data_dict[year][duration_minutes] = (
                                        pending_values[i] / (duration_minutes / 60)
                                    )
                                else:
                                    data_dict[year][duration_minutes] = pending_values[i]
                        pending_values = []
                    duration_minutes = new_duration

                if duration_minutes is None:
                    continue

                is_increasing = all(
                    x < y for x, y in zip(values['lone_decimals'], values['lone_decimals'][1:])
                )

                if is_increasing and len(values['lone_decimals']) == len(year_values):
                    # Full row of values — store immediately
                    for i, year in enumerate(year_values):
                        if convert_to_intensity:
                            data_dict[year][duration_minutes] = (
                                values['lone_decimals'][i] / (duration_minutes / 60)
                            )
                        else:
                            data_dict[year][duration_minutes] = values['lone_decimals'][i]
                    pending_values = []  # reset accumulator

                elif len(values['lone_decimals']) == 1:
                    # Single value — accumulate
                    pending_values.append(values['lone_decimals'][0])
                    if len(pending_values) == len(year_values):
                        for i, year in enumerate(year_values):
                            if convert_to_intensity:
                                data_dict[year][duration_minutes] = (
                                    pending_values[i] / (duration_minutes / 60)
                                )
                            else:
                                data_dict[year][duration_minutes] = pending_values[i]
                        pending_values = []

        # ------------------------------------------------------------------
        # Layout C: durations are lone ints, years are labels
        # ------------------------------------------------------------------
        elif (
            total_counts.get('lone_decimals_count', 0) > 0
            and total_counts.get('lone_ints_count', 0) > 0
            and total_counts.get('year_label_count', 0) > 0
            and total_counts['lone_decimals_count'] // total_counts['lone_ints_count']
                == total_counts['year_label_count']
        ):
            print("Layout C detected: lone ints are duration values, years as labels.")
            unit_candidates = total_values.get('duration_matches', [])
            if not unit_candidates:
                raise RainfallParseError("Layout C: no duration unit could be found.")
            unit = unit_candidates[0][1]
            print(f"Duration unit detected as: {unit!r}")

            year_values = sorted(year for year, _ in total_values.get('years', []))
            if not year_values:
                raise RainfallParseError("Layout C: no year values could be extracted.")

            self.years = year_values
            data_dict = {year: {} for year in year_values}
            duration_minutes = None  # carry-forward

            for row in inspection:
                counts = row['counts']
                values = row['values']

                # Duration is a lone int on this row
                if counts['lone_ints_count'] == 1:
                    candidate = values['lone_ints'][0]
                    converted = self._convert_duration_to_minutes(candidate, unit)
                    if converted is not None:
                        duration_minutes = converted

                if duration_minutes is None:
                    continue

                is_increasing = all(
                    x < y for x, y in zip(values['lone_decimals'], values['lone_decimals'][1:])
                )
                if is_increasing and len(values['lone_decimals']) == len(year_values):
                    for i, year in enumerate(year_values):
                        if convert_to_intensity:
                            data_dict[year][duration_minutes] = (
                                values['lone_decimals'][i] / (duration_minutes / 60)
                            )
                        else:
                            data_dict[year][duration_minutes] = values['lone_decimals'][i]

        # ------------------------------------------------------------------
        # No layout matched
        # ------------------------------------------------------------------
        else:
            raise RainfallParseError(
                "Could not determine the data layout from the provided string. "
                "Check that the data contains recognisable duration, year, and value fields."
            )

        if data_dict is None or not any(data_dict[y] for y in data_dict):
            raise RainfallParseError("Layout was detected but no data rows could be extracted.")

        self.data = data_dict
        return data_dict

# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------

MY_STRING = """
Duration Average recurrence interval (years)
1 2 5 10 25 50 100 200 500 1000
5-min 0.405 0.439 0.572 0.673 0.807 0.909 1.012 1.117 1.261 1.371
10-min 0.649 0.704 0.919 1.081 1.297 1.462 1.627 1.791 2.008 2.171
15-min 0.807 0.875 1.137 1.336 1.601 1.801 2.004 2.212 2.493 2.711
30-min 1.117 1.210 1.570 1.842 2.203 2.475 2.752 3.041 3.436 3.746
60-min 1.449 1.572 2.047 2.408 2.888 3.248 3.619 4.011 4.553 4.983
2-hr 1.773 1.935 2.555 3.031 3.671 4.159 4.669 5.215 5.977 6.588
3-hr 1.966 2.154 2.871 3.423 4.173 4.752 5.361 6.013 6.930 7.668
6-hr 2.323 2.558 3.446 4.135 5.077 5.810 6.586 7.419 8.591 9.536
12-hr 2.733 3.016 4.089 4.919 6.051 6.928 7.852 8.840 10.224 11.336
24-hr 3.191 3.522 4.776 5.747 7.069 8.096 9.175 10.321 11.921 13.201
48-hr 3.692 4.063 5.447 6.532 8.033 9.225 10.488 11.816 13.663 15.136
3-day 4.018 4.417 5.901 7.067 8.686 9.976 11.348 12.792 14.805 16.411
4-day 4.258 4.680 6.252 7.488 9.204 10.573 12.030 13.569 15.716 17.433
7-day 4.771 5.249 7.037 8.438 10.375 11.908 13.541 15.281 17.726 19.693
10-day 5.216 5.736 7.688 9.211 11.306 12.950 14.699 16.573 19.213 21.343
20-day 6.739 7.340 9.640 11.404 13.780 15.588 17.492 19.564 22.505 24.891
30-day 8.012 8.684 11.283 13.257 15.883 17.846 19.898 22.138 25.318 27.899
45-day 9.755 10.569 13.712 16.103 19.289 21.690 24.175 26.822 30.508 33.449
60-day 11.294 12.248 15.917 18.720 22.477 25.346 28.296 31.362 35.554 38.840
"""

if __name__ == "__main__":
    r = RainfallData()
    try:
        result = r.clean_arbitrary_data(MY_STRING, convert_to_intensity=True)
        print(result)
    except RainfallDataError as exc:
        print(f"[{exc.__class__.__name__}] {exc.message}")