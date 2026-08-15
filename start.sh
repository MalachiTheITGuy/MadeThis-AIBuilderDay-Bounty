source .venv/bin/activate
pip3 install -e ".[dev]"
pytest -q                     # schema + seed smoke tests
python3 seed_data.py           # build a deterministic synthetic world
python3 run.py                 # start the API on http://localhost:8000
