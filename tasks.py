# tasks.py
import io, os, uuid, shutil, tempfile, zipfile
from datetime import date

import nbformat
import papermill as pm
from nbconvert import PDFExporter
from traitlets.config import Config

from rainfall_data import RainfallData, RainfallDataError
from idf_analysis import run_idf_analysis

_TEMPLATE_NB = os.path.join(os.path.dirname(__file__), "idf_report_template.ipynb")


def generate_report_task(body: dict) -> bytes:
    """
    Runs the full IDF analysis + PDF generation.
    Returns raw ZIP bytes on success, raises on failure.
    Called by the RQ worker in a separate process.
    """
    r = RainfallData()

    if "rainfall_data" in body:
        data_dict = r.clean_arbitrary_data(
            body["rainfall_data"],
            convert_to_intensity=body.get("convert_to_intensity", True),
        )
    elif "lat" in body and "lon" in body:
        r.get_from_noaa(float(body["lat"]), float(body["lon"]))
        data_dict = r.data
    else:
        raise ValueError("Provide either 'rainfall_data' or 'lat'/'lon'.")

    tmp_dir = tempfile.mkdtemp(prefix=f"idf_{uuid.uuid4().hex}_")
    try:
        results = run_idf_analysis(data_dict, tmp_dir)

        executed_nb_path = os.path.join(tmp_dir, "executed.ipynb")
        pm.execute_notebook(
            _TEMPLATE_NB,
            executed_nb_path,
            parameters={
                "params":           results.params,
                "figures_b64":      results.figures_b64,
                "years":            results.years,
                "data_dict":        data_dict,
                "lat":              body.get("lat", ""),
                "lon":              body.get("lon", ""),
                "project_name":     body.get("project_name", ""),
                "project_location": body.get("project_location", ""),
                "project_date":     body.get("project_date", str(date.today())),
                "job_number":       body.get("job_number", ""),
            },
            kernel_name="python3",
            cwd=os.path.dirname(__file__),
        )

        cfg = Config()
        pdf_exporter = PDFExporter(config=cfg)
        pdf_exporter.exclude_input = True
        pdf_exporter.exclude_input_prompt = True
        pdf_exporter.exclude_output_prompt = True

        with open(executed_nb_path) as f:
            nb = nbformat.read(f, as_version=4)

        nb.metadata["title"] = "EBD Value Report"
        pdf_bytes, _ = pdf_exporter.from_notebook_node(nb)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("EBD_Report.pdf", pdf_bytes)
            for key, csv_path in results.csv_paths.items():
                if os.path.exists(csv_path):
                    zf.write(csv_path, os.path.basename(csv_path))

        return zip_buffer.getvalue(), list(results.errors)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)