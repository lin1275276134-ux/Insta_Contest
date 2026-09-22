"""Experimental X5 catalog reader; does not certify complete capture groups."""
import argparse
import json
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener
from tools.probes.inspect_device import NoRedirect, base_report, redact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = base_report('catalog_experiment')
    report.update(pages=[], termination='page_limit', completeness='unverified')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    seen = set()
    start = 0
    for _ in range(100):
        body = dict(name='camera.listFiles', parameters=dict(
            fileType='video', startPosition=start, entryCount=20, maxThumbSize=None))
        page = dict(request=body)
        try:
            req = Request('http://192.168.42.1/osc/commands/execute',
                data=json.dumps(body).encode(), headers={'Content-Type': 'application/json;charset=utf-8',
                'Accept': 'application/json', 'X-XSRF-Protected': '1'})
            with opener.open(req, timeout=8) as response:
                page['status'] = response.status
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError('oversize')
                payload = json.loads(raw)
            page['response'] = redact(payload)
            report['pages'].append(page)
            if payload.get('state') != 'done':
                report['termination'] = 'device_error'
                break
            entries = payload['results']['entries']
            if not entries:
                report['termination'] = 'empty_page'
                break
            keys = [entry['_localFileUrl'] for entry in entries]
            if any(key in seen for key in keys) or len(set(keys)) != len(keys):
                report['termination'] = 'duplicate_entries'
                break
            seen.update(keys)
            # This firmware returns page count as totalEntries. Never stop on that field.
            start += len(entries)
            # Firmware can cap a page below entryCount; keep reading until an empty page.
        except (OSError, ValueError, KeyError, TypeError) as exc:
            page['error'] = type(exc).__name__
            if not report['pages'] or report['pages'][-1] is not page:
                report['pages'].append(page)
            report['termination'] = 'request_failed'
            break
    report['unique_entries'] = len(seen)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(output=str(args.output), entries=len(seen), termination=report['termination'])))


if __name__ == '__main__':
    main()
