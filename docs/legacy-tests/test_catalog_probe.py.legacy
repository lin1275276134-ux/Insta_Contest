import json
import sys
from tools.probes import catalog_probe


def test_short_page_and_page_total_do_not_stop_scan(tmp_path, monkeypatch):
    offsets = []

    class Response:
        status = 200

        def __init__(self, start):
            self.start = start

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            entries = [{'_localFileUrl': f'/DCIM/{i}'}
                       for i in range(self.start, min(self.start + 15, 31))]
            return json.dumps(dict(state='done', results=dict(
                entries=entries, totalEntries=len(entries)))).encode()

    class Opener:
        def open(self, req, timeout):
            start = json.loads(req.data)['parameters']['startPosition']
            offsets.append(start)
            return Response(start)

    output = tmp_path / 'catalog.json'
    monkeypatch.setattr(catalog_probe, 'build_opener', lambda *args: Opener())
    monkeypatch.setattr(sys, 'argv', ['probe', '--output', str(output)])
    catalog_probe.main()
    report = json.loads(output.read_text())
    assert offsets == [0, 15, 30, 31]
    assert report['unique_entries'] == 31
    assert report['termination'] == 'empty_page'
    assert report['completeness'] == 'unverified'
