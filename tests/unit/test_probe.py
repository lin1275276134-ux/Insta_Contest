import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from tools.probes.inspect_device import device_report, media_report


def test_device_records_errors_and_redacts_identifiers():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(('GET', self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'model': 'X5', 'serialNumber': 'secret',
                                       'nested': {'wifiPassword': 'secret'}}).encode())

        def do_POST(self):
            requests.append(('POST', self.path))
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'private server details')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = device_report(f'http://127.0.0.1:{server.server_port}', 2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert requests == [('GET', '/osc/info'), ('POST', '/osc/state')]
    assert report['requests'][1]['error'] == 'HTTPError'
    assert report['requests'][1]['status'] == 503
    assert 'secret' not in json.dumps(report)
    assert 'private server' not in json.dumps(report)
    assert all(value == 'unknown' for value in report['capabilities'].values())
    assert report['gate_status'] == 'unverified'


def test_corrupt_media_is_not_passed(tmp_path):
    source = tmp_path / 'broken.insv'
    source.write_bytes(b'not a video')
    report = media_report([source], 5)
    assert report['files'][0]['status'] == 'probe_failed'
    assert report['files'][0]['sha256']
    assert report['gate_status'] == 'unverified'


def test_device_rejects_credentials_and_paths():
    import pytest
    for url in ['http://user:password@127.0.0.1', 'http://127.0.0.1/delete',
                'file:///tmp/test', 'http://127.0.0.1/?token=secret']:
        with pytest.raises(ValueError):
            device_report(url, 1)


def test_readable_video_still_requires_projection_and_group_validation(tmp_path):
    import subprocess
    source = tmp_path / 'sample.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=32x32:d=0.2',
                    '-c:v', 'libx264', str(source)], check=True, timeout=30)
    report = media_report([source], 5)
    assert report['files'][0]['status'] == 'metadata_only'
    assert report['files'][0]['projection'] == 'unknown'
    assert report['files'][0]['group_completeness'] == 'unknown'
    assert report['gate_status'] == 'unverified'
    assert str(tmp_path) not in json.dumps(report)
