"""Explicit local simulator. Its manifest is test input, not an X5 protocol."""
import json
import shutil
import hashlib
from backend.app.schema import Group, DomainError


def group_key(g):
    raw = f"{g['storage_epoch']}:{g['id']}:{g['revision']}"
    return "groupversion_" + hashlib.sha256(raw.encode()).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class SimulatorCamera:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir / 'simulator'

    def read(self):
        if not self.settings.simulation:
            raise DomainError('CAPABILITY_UNVERIFIED', 'X5 协议尚待 G0/G1 验证，请先配置设备探测',
                              action='configure_device')
        manifest = self.root / 'catalog.json'
        if not manifest.exists():
            raise DomainError('DEVICE_DISCONNECTED', '尚无模拟目录，请运行模拟素材脚本',
                              retryable=True, action='seed_simulator')
        data = json.loads(manifest.read_text())
        if not data.get('connected', True):
            raise DomainError('DEVICE_DISCONNECTED', '模拟相机断开', retryable=True, action='reconnect')
        if data.get('fail_page'):
            raise DomainError('CATALOG_INCOMPLETE', '模拟目录分页失败，保留原基线', retryable=True)
        groups = [Group.model_validate(g).model_dump() for g in data['groups']]
        seen = {}
        for g in groups:
            key = (g['storage_epoch'], g['id'])
            if key in seen and seen[key] != g:
                raise DomainError('CATALOG_INCOMPLETE', '同次扫描发现相互矛盾的目录版本', retryable=True)
            seen[key] = g
        return list(seen.values())

    def scan(self):
        first, second = self.read(), self.read()
        if first != second:
            raise DomainError('CATALOG_INCOMPLETE', '目录发生变化，需重新扫描', retryable=True)
        return second

    def download(self, group, target):
        current = {group_key(g): g for g in self.read()}
        key = group_key(group)
        if key not in current or current[key] != group:
            raise DomainError('DOWNLOAD_INCOMPLETE', '远端文件版本已变化', retryable=True)
        if not group['closed'] or not group['complete']:
            raise DomainError('GROUP_NOT_READY', '录制或文件组尚未完成', retryable=True)
        target.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, (member, size) in enumerate(zip(group['members'], group['sizes'])):
            source = self.root / member
            if source.is_symlink() or not source.is_file() or source.stat().st_size != size:
                raise DomainError('DOWNLOAD_INCOMPLETE', '成员缺失或传输长度不匹配', retryable=True)
            dest = target / f'{i}.part'
            shutil.copyfile(source, dest)
            if dest.stat().st_size != size or digest(dest) != digest(source):
                raise DomainError('DOWNLOAD_INCOMPLETE', '下载校验失败', retryable=True)
            paths.append(dest)
        after = {group_key(g): g for g in self.read()}
        if after.get(key) != group:
            raise DomainError('DOWNLOAD_INCOMPLETE', '下载中远端版本变化', retryable=True)
        return paths
