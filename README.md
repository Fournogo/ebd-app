# EBD Value Generator

All commands must be executed in the main project directory.

To start docker container for the first time do: docker compose up --build -d
To shut down the container do: docker compose down
To restart the container do: docker compose up -d

To rebuild the front end, cd into the "front-end" directory and do "npm run build"

NOTE: On a new install, you must create a .env file and fill it with: VITE_MAPTILER_API_KEY=apikeyhere
Be sure to build the container AFTER doing this.

This app uses a Python Flask architecture to handle web requests. 
App.py serves up front end files over http and allows React to handle URL routing.
The "/generate-report" route is in "routes.py". This is the function that will be called when the user presses the generate report button.

"generate_report()" creates a job in Redis to run in the background. The Redis job will include "generate_report_task()" from tasks.py. This is all done to ensure multiple users can make requests at the same time.
Jobs are assigned an ID which is returned to the front end. The front end polls "/report-status/<job-id>" to request a download once the job is done. 

The "generate_report_task()" function uses several classes from "rainfall_data.py" to process or request data. Once the data is cleaned, it is sent to "run_idf_analysis()" found in "idf_analysis.py". This module performs the non-linear regression and returns values and base64 PNG strings. Values and PNG strings are then sent to nbconvert where they will be injected into "idf_report_template.ipynb" for execution. The executed notebook will be saved to a temp file then rendered as a PDF with nbconvert. Finally the PDF and csv files are zipped and returned, thus completing the Redis task. The next poll from the front end will be handed the completed zip file.
