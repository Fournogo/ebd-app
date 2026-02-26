"""
test_report.py
--------------
Sends a POST request to /generate-report and saves the returned ZIP file.

Usage:
    python test_report.py                        # uses sample data below
    python test_report.py --lat 47.23 --lon -111.59
    python test_report.py --input my_data.txt    # raw IDF string from a file

The downloaded ZIP will be saved to the current directory as:
    IDF_Analysis_Results.zip
"""

import argparse
import sys
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:5000"
OUTPUT_FILE = "IDF_Analysis_Results.zip"

# Sample IDF data used when no --lat/--lon or --input is provided.
# Replace with data representative of your actual input format.
SAMPLE_RAINFALL_DATA = """\
Duration, 2-yr, 5-yr, 10-yr, 25-yr, 50-yr, 100-yr
5,        0.43, 0.54, 0.62,  0.73,  0.82,  0.91
10,       0.72, 0.90, 1.04,  1.23,  1.37,  1.52
15,       0.89, 1.12, 1.29,  1.52,  1.70,  1.89
30,       1.17, 1.47, 1.69,  2.00,  2.23,  2.47
60,       1.44, 1.81, 2.08,  2.46,  2.74,  3.04
120,      1.67, 2.10, 2.42,  2.86,  3.19,  3.54
360,      2.01, 2.53, 2.91,  3.44,  3.84,  4.26
720,      2.28, 2.87, 3.30,  3.90,  4.35,  4.83
1440,     2.56, 3.22, 3.71,  4.38,  4.89,  5.42
"""

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_payload(args: argparse.Namespace) -> dict:
    payload = {
        "project_name":     args.project_name,
        "project_location": args.project_location,
        "project_date":     args.project_date,
        "job_number":       args.job_number,
    }

    if args.lat is not None and args.lon is not None:
        payload["lat"] = args.lat
        payload["lon"] = args.lon
    elif args.input:
        with open(args.input, "r") as f:
            payload["rainfall_data"] = f.read()
    else:
        print("No --lat/--lon or --input provided — using built-in sample data.\n")
        payload["rainfall_data"] = SAMPLE_RAINFALL_DATA

    return payload


def main():
    parser = argparse.ArgumentParser(description="Test the /generate-report endpoint.")
    parser.add_argument("--url",              default=BASE_URL,              help="Base URL of the Flask app")
    parser.add_argument("--lat",              type=float, default=None,      help="Latitude (NOAA fetch)")
    parser.add_argument("--lon",              type=float, default=None,      help="Longitude (NOAA fetch)")
    parser.add_argument("--input",            default=None,                  help="Path to a raw IDF text file")
    parser.add_argument("--output",           default=OUTPUT_FILE,           help="Where to save the ZIP")
    parser.add_argument("--project-name",     default="Test IDF Report",     help="Project name")
    parser.add_argument("--project-location", default="Test Location",       help="Project location")
    parser.add_argument("--project-date",     default="2026-02-24",          help="Project date (YYYY-MM-DD)")
    parser.add_argument("--job-number",       default="",                    help="Job number")
    args = parser.parse_args()

    payload = build_payload(args)
    endpoint = f"{args.url}/generate-report"

    print(f"POST {endpoint}")
    print(f"Payload keys: {list(payload.keys())}\n")

    try:
        response = requests.post(endpoint, json=payload, timeout=120)
    except requests.ConnectionError:
        print(f"ERROR: Could not connect to {endpoint}")
        print("Make sure the Flask app is running (`python app.py`).")
        sys.exit(1)

    # Surface any non-fatal analysis warnings from the response header
    warnings = response.headers.get("X-Analysis-Warnings")
    if warnings:
        print(f"⚠  Analysis warnings: {warnings}\n")

    if response.status_code == 200:
        with open(args.output, "wb") as f:
            f.write(response.content)
        size_kb = len(response.content) / 1024
        print(f"✓  Success — saved {args.output} ({size_kb:.1f} KB)")
    else:
        print(f"✗  Request failed — HTTP {response.status_code}")
        try:
            print(response.json())
        except Exception:
            print(response.text)
        sys.exit(1)


if __name__ == "__main__":
    main()
