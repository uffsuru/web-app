#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

# Run database initializations
python -c "from app import app, init_db; app.app_context().push(); init_db()"
python -c "from app import app, create_sample_data; app.app_context().push(); create_sample_data()"