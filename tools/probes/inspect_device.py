"""T00 evidence collection; successful reads never imply G0/G1 acceptance."""
import argparse
import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def redact(value):
    if isinstance(value, dict):
        return {key: '[redacted]' if any(word in key.lower() for word in
                ('serial', 'password', 'token', 'secret', 'ssid', 'authorization', 'gps'))
                else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and '://' in value:
        return '[redacted URL]'
    return value


def base_report(kind):
    return dict(kind=kind, captured_at=datetime.now(timezone.utc).isoformat(),
                host=dict(system=platform.system(), release=platform.release(), machine=platform.machine()),
                gate_status='unverified')


def device_report(base_url, timeout):
    parsed = urlsplit(base_url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('设备地址仅允许 http(s) 主机及端口，不允许凭据、路径或查询参数')
    opener = build_opener(NoRedirect(), ProxyHandler({}))
    report = base_report('device')
    report['capabilities'] = dict.fromkeys(('history_video_listing', 'listing_during_recording',
        'download_during_recording', 'group_metadata', 'readiness_signal'), 'unknown')
    report['requests'] = []
    for method, path in [('GET', '/osc/info'), ('POST', '/osc/state')]:
        entry = dict(method=method, path=path)
        request = Request(base_url.rstrip('/') + path, method=method,
                          data=b'{}' if method == 'POST' else None,
                          headers={'Content-Type': 'application/json;charset=utf-8',
                                   'Accept': 'application/json', 'X-XSRF-Protected': '1'})
        try:
            with opener.open(request, timeout=timeout) as response:
                entry['status'] = response.status
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError('response too large')
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError('expected object')
                entry['response'] = redact(payload)
                if 'error' in payload:
                    entry['error'] = 'DeviceError'
        except (OSError, ValueError) as exc:
            entry['error'] = type(exc).__name__
            if isinstance(exc, HTTPError):
                entry['status'] = exc.code
        report['requests'].append(entry)
    return report


def media_report(paths, timeout):
    report = base_report('media')
    report['files'] = []
    for source in paths:
        source = Path(source).resolve()
        item = dict(name=source.name, projection='unknown', group_completeness='unknown')
        try:
            digest = hashlib.sha256()
            with source.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            item.update(bytes=source.stat().st_size, sha256=digest.hexdigest())
            result = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                '-of', 'json', str(source)], capture_output=True, check=True, timeout=timeout)
            raw = json.loads(result.stdout)
            # Keep technical fields only: container tags can contain paths, location and device IDs.
            item['format'] = {key: raw.get('format', {}).get(key) for key in
                              ('format_name', 'duration', 'size', 'bit_rate')}
            item['streams'] = [{key: stream[key] for key in ('index', 'codec_type', 'codec_name',
                'width', 'height', 'duration', 'r_frame_rate', 'pix_fmt') if key in stream}
                for stream in raw.get('streams', [])]
            item['status'] = 'metadata_only'
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            item.update(status='probe_failed', error=type(exc).__name__)
        report['files'].append(item)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=30)
    modes = parser.add_subparsers(dest='mode', required=True)
    modes.add_parser('device').add_argument('--base-url', required=True)
    modes.add_parser('media').add_argument('files', nargs='+', type=Path)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('timeout must be positive')
    try:
        report = (device_report(args.base_url, args.timeout) if args.mode == 'device'
                  else media_report(args.files, args.timeout))
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Do not overwrite an earlier probe or source file.
    with args.output.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    entries = report.get('requests', report.get('files', []))
    return 1 if any('error' in item for item in entries) else 0


if __name__ == '__main__':
    raise SystemExit(main())
