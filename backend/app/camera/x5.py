"""Read-only OSC adapter. Readiness and single-lens policies require live verification."""
import hashlib
import json
import math
import re
import shutil
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener
from backend.app.schema import DomainError
from backend.app.storage.repository import uid


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def token(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class X5Camera:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.opener = build_opener(NoRedirect(), ProxyHandler({}))
        self.epoch = uid('storage')
        self.observed = {}
        self.members = {}
        self.info = None
        self.previous = set()
        parsed = urlsplit(settings.x5_base_url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('BOLD_X5_BASE_URL must be an HTTP(S) origin without credentials')
        self.base_url = settings.x5_base_url.rstrip('/')

    def request(self, path, body=None):
        request = Request(self.base_url + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json;charset=utf-8',
                                   'Accept': 'application/json', 'X-XSRF-Protected': '1'})
        try:
            with self.opener.open(request, timeout=self.settings.x5_timeout) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('oversize')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError('invalid response')
            if result.get('error') or result.get('state') == 'error':
                raise DomainError('CAPABILITY_UNVERIFIED', '相机不支持请求的只读能力', action='check_device')
            return result
        except (OSError, ValueError) as exc:
            raise DomainError('DEVICE_DISCONNECTED', '无法读取 X5，请检查相机 Wi-Fi 连接',
                              retryable=True, action='reconnect') from exc

    def connect(self):
        with self.lock:
            info = self.request('/osc/info')
            if info.get('model') != 'Insta360 X5':
                raise DomainError('CAPABILITY_UNVERIFIED', '当前只验证了 X5 设备', action='check_device')
            identity = token([info.get('model'), info.get('serialNumber')])
            if self.info and self.info['identity'] != identity:
                self.reset_storage()
            self.info = dict(identity=identity, firmware=info.get('firmwareVersion', 'unknown'))
            return self.info

    def reset_storage(self):
        self.epoch = uid('storage')
        self.observed.clear()
        self.members.clear()
        self.previous.clear()

    def catalog(self):
        rows, seen = [], set()
        for _ in range(100):
            response = self.request('/osc/commands/execute', dict(name='camera.listFiles', parameters=dict(
                fileType='video', startPosition=len(rows), entryCount=20, maxThumbSize=None)))
            try:
                if response.get('state') != 'done':
                    raise ValueError('incomplete')
                entries = response['results']['entries']
                if not isinstance(entries, list):
                    raise ValueError('invalid entries')
                if not entries:
                    return rows
                for item in entries:
                    path = item['_localFileUrl']
                    if (not isinstance(path, str) or not re.fullmatch(r'/DCIM/Camera01/[A-Za-z0-9_-]+\.(mp4|insv|lrv)', path)
                            or path in seen or type(item['size']) not in (int, float)
                            or not math.isfinite(item['size']) or item['size'] < 0
                            or item['size'] != int(item['size']) or item['size'] > 2**53):
                        raise ValueError('invalid or duplicate member')
                    seen.add(path)
                    rows.append(dict(path=path, size=int(item['size'])))
            except (KeyError, TypeError, ValueError) as exc:
                raise DomainError('CATALOG_INCOMPLETE', '相机目录异常，原同步基线保留', retryable=True) from exc
        raise DomainError('CATALOG_INCOMPLETE', '相机目录超过扫描页数限制', action='check_device')

    def groups(self, rows):
        buckets = {}
        for item in rows:
            path = item.get('path', item.get('_localFileUrl'))
            name = path.rsplit('/', 1)[-1]
            match = re.fullmatch(r'(VID|LRV)_(\d{8}_\d{6})_(?:(\d{2})_)?(\d+)\.(mp4|insv|lrv)', name)
            key = f'{match[2]}_{match[4]}' if match else name
            buckets.setdefault(key, []).append(dict(path=path, size=item['size']))
        groups = []
        now = time.monotonic()
        for key, entries in sorted(buckets.items()):
            entries = sorted(entries, key=lambda e: e['path'])
            originals = [e for e in entries if e['path'].endswith(('.mp4', '.insv'))
                         and '/VID_' in e['path']]
            previews = [e for e in entries if e['path'].endswith('.lrv')]
            revision = token(entries)
            prior = self.observed.get(key)
            stable = prior is not None and prior[0] == revision and now - prior[1] >= self.settings.x5_stable_seconds
            if prior is None or prior[0] != revision:
                self.observed[key] = (revision, now)
            # Scope is deliberately limited to one source plus its preview, as verified on 078/079.
            complete = len(originals) == 1 and len(previews) == 1 and len(entries) == 2 and all(e['size'] > 0 for e in entries)
            members = ['member_' + token(e['path']) for e in entries]
            self.members.update({mid: e for mid, e in zip(members, entries)})
            media = [mid for mid, e in zip(members, entries) if e in originals]
            panorama = any(e['path'].endswith('.insv') for e in originals)
            projection = ('panorama' if panorama else 'rectilinear'
                          if self.settings.x5_single_lens_confirmed and complete else 'unknown')
            groups.append(dict(id='x5_' + token(key), revision=revision, name=(originals or entries)[0]['path'].rsplit('/', 1)[-1],
                storage_epoch=self.epoch, members=members, sizes=[max(1, e['size']) for e in entries],
                media_members=media, closed=bool(stable and complete and self.settings.x5_readiness_verified),
                complete=complete, projection=projection, scenario='unrelated'))
        return groups

    def read(self):
        return self.scan()

    def scan(self):
        with self.lock:
            try:
                self.connect()
                state = self.request('/osc/state', {}).get('state', {})
                if state.get('_cardState') != 'pass':
                    raise DomainError('DEVICE_DISCONNECTED', '相机存储卡不可用', action='check_card', retryable=True)
                first, second = self.catalog(), self.catalog()
                if first != second:
                    raise DomainError('CATALOG_INCOMPLETE', '扫描期间目录变化，请等待下一次完整扫描', retryable=True)
                paths = {item['path'] for item in second}
                if self.previous - paths:
                    self.reset_storage()  # Loss of entries may mean card replacement; require scope again.
                self.previous = paths
                return self.groups(second)
            except DomainError as exc:
                if exc.code == 'DEVICE_DISCONNECTED':
                    self.reset_storage()
                raise

    def download(self, group, target):
        with self.lock:
            current = {g['id']: g for g in self.scan()}.get(group['id'])
            if not current or any(current[k] != group[k] for k in ('revision', 'storage_epoch', 'members', 'sizes')):
                raise DomainError('DOWNLOAD_INCOMPLETE', '远端素材版本已变化', retryable=True)
            if not current['closed'] or not current['complete']:
                raise DomainError('GROUP_NOT_READY', '尚未验证相机文件组已结束写入', retryable=True)
            if sum(group['sizes']) > self.settings.max_source_bytes:
                raise DomainError('MEDIA_UNSUPPORTED', '源文件组超过配置大小上限', action='configure_limits')
            target.mkdir(parents=True, exist_ok=True)
            downloaded = []
            try:
                for i, mid in enumerate(group['members']):
                    entry = self.members[mid]
                    part = target / f'{i}.part'
                    count = 0
                    with self.opener.open(self.base_url + entry['path'], timeout=self.settings.x5_timeout) as response, part.open('wb') as out:
                        while chunk := response.read(1024 * 1024):
                            count += len(chunk)
                            if count > entry['size']:
                                raise DomainError('DOWNLOAD_INCOMPLETE', '相机文件下载期间增长', retryable=True)
                            if shutil.disk_usage(target).free < self.settings.min_free_bytes + len(chunk):
                                raise DomainError('STORAGE_FULL', '下载空间不足，请清理磁盘后重试', action='free_space')
                            out.write(chunk)
                    if count != entry['size']:
                        raise DomainError('DOWNLOAD_INCOMPLETE', '下载长度不完整', retryable=True)
                    downloaded.append(part)
                after = {g['id']: g for g in self.scan()}.get(group['id'])
                if not after or after['revision'] != group['revision'] or after['storage_epoch'] != group['storage_epoch']:
                    raise DomainError('DOWNLOAD_INCOMPLETE', '下载后目录版本变化', retryable=True)
                return downloaded
            except OSError as exc:
                code = 'STORAGE_FULL' if exc.errno == 28 else 'DOWNLOAD_INCOMPLETE'
                raise DomainError(code, '下载中断，请检查相机连接与磁盘', retryable=True) from exc
