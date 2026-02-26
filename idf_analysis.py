"""
idf_analysis.py
---------------
Performs non-linear regression on IDF (intensity-duration-frequency) rainfall
data and produces all outputs required by the Flask report route:

* Fitted EBD curve parameters (e, b, d) for each return period
* Matplotlib figures (one per return period) as base64 PNG strings for embedding
* Two CSV files written to a caller-supplied temp directory:
    - "Output Intensity Values.csv"  — original intensities
    - "Output EBD Values.csv"        — fitted parameters
    - "Computed Errors.csv"          — per-duration residual errors

Public API
----------
run_idf_analysis(data_dict, output_dir) -> IdfResults
"""

import csv
import io
import base64
import os
import re

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # non-interactive backend — required for Flask
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit, OptimizeWarning
from sklearn.metrics import mean_squared_error
from dataclasses import dataclass, field
from typing import Any
import warnings


# ---------------------------------------------------------------------------
# EBD model  (top-level so it is never re-created inside loops)
# ---------------------------------------------------------------------------

def model_function(x: np.ndarray, b: float, d: float, e: float) -> np.ndarray:
    """Empirical block-duration (EBD) intensity model.

    i(t) = b / (t + d)^e

    Parameters
    ----------
    x : np.ndarray
        Duration values in minutes.
    b, d, e : float
        Fitted EBD parameters.

    Returns
    -------
    np.ndarray
        Predicted intensity values (in/hr).
    """
    return b / (x + d) ** e


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class IdfResults:
    """All outputs produced by :func:`run_idf_analysis`.

    Attributes
    ----------
    years : list[int]
        Return-period years in ascending order.
    params : dict[int, dict]
        ``{year: {"e": float, "b": float, "d": float, "mse": float}}``
    figures_b64 : dict[int, str]
        ``{year: base64_png_string}`` — one figure per return period.
    csv_paths : dict[str, str]
        ``{"intensity": path, "ebd": path, "errors": path}``
    errors : list[str]
        Any non-fatal warnings collected during processing.
    """
    years: list[int] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    figures_b64: dict = field(default_factory=dict)
    csv_paths: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def minutes_to_labels(minutes: list[float]) -> list[str]:
    """Convert a list of minute values to human-readable duration labels.

    Parameters
    ----------
    minutes : list[float]
        Duration values in minutes.

    Returns
    -------
    list[str]
        Labels such as ``"30-min"``, ``"2-hr"``, ``"1-day"``.
    """
    labels = []
    for m in minutes:
        if m <= 60:
            labels.append(f"{int(m)}-min")
        elif m < 1440:
            labels.append(f"{int(m // 60)}-hr")
        else:
            labels.append(f"{int(m // 1440)}-day")
    return labels


def _figure_to_b64(fig: plt.Figure) -> str:
    """Render a Matplotlib figure to a base64-encoded PNG string.

    Parameters
    ----------
    fig : plt.Figure
        The figure to encode.

    Returns
    -------
    str
        Base64 PNG string suitable for an HTML ``<img src="data:...">`` tag.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return encoded


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

def _write_intensity_csv(years: list[int], data_dict: dict, path: str) -> None:
    """Write original IDF intensity values to a CSV file.

    Parameters
    ----------
    years : list[int]
        Return-period years to include.
    data_dict : dict
        Cleaned IDF data dict ``{year: {duration_min: intensity, ...}, ...}``.
    path : str
        Destination file path.
    """
    header = ["Duration"] + [f"{y}-yr" for y in years]
    rows = [header]

    # Build row stubs from the first year's durations
    first_year_minutes = list(data_dict[years[0]].keys())
    labels = minutes_to_labels(first_year_minutes)
    for label in labels:
        rows.append([label])

    for year in years:
        minutes = list(data_dict[year].keys())
        for i, minute in enumerate(minutes):
            rows[i + 1].append(round(data_dict[year][minute], 6))

    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)


def _write_ebd_csv(years: list[int], params: dict, path: str) -> None:
    """Write fitted EBD parameter values to a CSV file.

    Parameters
    ----------
    years : list[int]
        Return-period years.
    params : dict
        ``{year: {"e": float, "b": float, "d": float, "mse": float}}``
    path : str
        Destination file path.
    """
    header = ["Variable"] + [f"{y}-yr" for y in years]
    rows = [
        header,
        ["e"] + [params[y]["e"] for y in years],
        ["b"] + [params[y]["b"] for y in years],
        ["d"] + [params[y]["d"] for y in years],
    ]
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)


def _write_errors_csv(val_output: pd.DataFrame, path: str) -> None:
    """Write per-duration residual errors DataFrame to a CSV file.

    Parameters
    ----------
    val_output : pd.DataFrame
        DataFrame with a ``Duration`` column and one column per return period.
    path : str
        Destination file path.
    """
    val_output.to_csv(path, index=False, float_format="%.6f")


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def run_idf_analysis(data_dict: dict, output_dir: str) -> IdfResults:
    """Run EBD regression on all return periods and produce all report outputs.

    Moves all computation (scipy curve fitting, figure generation, CSV writing)
    out of the notebook so the notebook template is purely presentational.

    Parameters
    ----------
    data_dict : dict
        Cleaned IDF data ``{return_period_yr: {duration_min: intensity, ...}, ...}``.
        Produced by :class:`RainfallData`.
    output_dir : str
        Path to a writable directory (typically a ``tempfile.mkdtemp()`` result)
        where CSV files will be written.

    Returns
    -------
    IdfResults
        Dataclass containing params, base64 figures, CSV paths, and any
        non-fatal warnings.

    Raises
    ------
    ValueError
        If ``data_dict`` is empty or ``output_dir`` does not exist.
    RuntimeError
        If curve fitting fails for every return period.
    """
    if not data_dict:
        raise ValueError("data_dict is empty — cannot run analysis.")
    if not os.path.isdir(output_dir):
        raise ValueError(f"output_dir does not exist: {output_dir!r}")

    years = sorted(data_dict.keys())
    results = IdfResults(years=years)

    val_output = pd.DataFrame()
    initial_guess = [75.5, 18.6, 0.88]
    fit_failures = 0

    for year in years:
        minutes = np.array(list(data_dict[year].keys()), dtype=float)
        intensity = np.array(list(data_dict[year].values()), dtype=float)

        # --- Curve fitting ---------------------------------------------------
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", OptimizeWarning)
                popt, _ = curve_fit(
                    model_function, minutes, intensity,
                    p0=initial_guess, maxfev=10_000,
                    bounds=(0, np.inf)
                )
        except (RuntimeError, OptimizeWarning, ValueError) as exc:
            msg = f"{year}-yr: curve_fit failed — {exc}"
            results.errors.append(msg)
            fit_failures += 1
            continue

        b, d, e = popt

        # --- Diagnostics -----------------------------------------------------
        predicted = model_function(minutes, b, d, e)
        mse = mean_squared_error(intensity, predicted)
        errors = intensity - predicted

        results.params[year] = {"e": e, "b": b, "d": d, "mse": mse}

        print(f"{year}-YR EBD Values:")
        print(f"  E = {e:.15f}")
        print(f"  B = {b:.15f}")
        print(f"  D = {d:.15f}")
        print(f"  Mean Sq Error: {mse}\n")

        # --- Residuals DataFrame ---------------------------------------------
        if val_output.empty:
            val_output["Duration"] = minutes_to_labels(minutes.tolist())
        val_output[f"{year}-yr"] = errors

        # --- Figure ----------------------------------------------------------
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.scatter(minutes, intensity, c="orange", s=50, label="Known Intensity Values", zorder=3)
        ax.set_xscale("log")
        ax.set_xlabel("Duration (min)")
        ax.set_ylabel("Intensity (in/hr)")
        ax.set_title(f"{year}-YR Intensity-Duration Curve")
        ax.grid(True, alpha=0.3)

        minutes_smooth = np.logspace(np.log10(minutes.min()), np.log10(minutes.max()), 100)
        ax.plot(
            minutes_smooth,
            model_function(minutes_smooth, b, d, e),
            "b-", linewidth=2, label="Fitted EBD Function"
        )
        ax.legend()
        fig.tight_layout()
        results.figures_b64[year] = _figure_to_b64(fig)

    if fit_failures == len(years):
        raise RuntimeError("Curve fitting failed for every return period. Check your input data.")

    # --- Write CSVs ----------------------------------------------------------
    intensity_path = os.path.join(output_dir, "Output Intensity Values.csv")
    ebd_path = os.path.join(output_dir, "Output EBD Values.csv")
    errors_path = os.path.join(output_dir, "Computed Errors.csv")

    _write_intensity_csv(years, data_dict, intensity_path)
    _write_ebd_csv(years, results.params, ebd_path)

    if not val_output.empty:
        _write_errors_csv(val_output, errors_path)

    results.csv_paths = {
        "intensity": intensity_path,
        "ebd": ebd_path,
        "errors": errors_path,
    }

    return results

if __name__ == "__main__":
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
    from rainfall_data import RainfallData
    r = RainfallData()
    result = r.clean_arbitrary_data(MY_STRING, convert_to_intensity=True)
    idf_results = run_idf_analysis(result, '/home/scrump/containers/ebd-app/test_dir')
    pass