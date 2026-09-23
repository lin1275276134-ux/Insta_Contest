import json
import os
from pathlib import Path
import tempfile
os.environ['BOLD_OPENAPI_ONLY'] = '1'
from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app import schema

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temp:
    app = create_app(Settings(data_dir=Path(temp)), run_worker=False)
    (root / 'contracts/openapi.json').write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + '\n')
for name in ('Evidence', 'Shot', 'Snapshot', 'Job', 'Clip', 'ImportBatch'):
    (root / f'contracts/schemas/{name}.json').write_text(
        json.dumps(getattr(schema, name).model_json_schema(), ensure_ascii=False, indent=2) + '\n')
