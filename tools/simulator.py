"""Test fixture authoring; this script never contacts or controls a camera."""
import argparse
import json
import os
import subprocess
from pathlib import Path
from backend.app.schema import Group
from backend.app.storage.repository import uid


def write(root, data):
    root.mkdir(parents=True, exist_ok=True)
    temp = root / 'catalog.json.tmp'
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temp.replace(root / 'catalog.json')


def add(root, scenario, closed=True):
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'catalog.json'
    data = json.loads(path.read_text()) if path.exists() else dict(connected=True, groups=[])
    member = uid('video')
    color = {'materials': 'steelblue', 'result': 'seagreen', 'clear': 'orange',
             'occluded': 'darkred', 'uncertain': 'gray', 'unrelated': 'purple'}[scenario]
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'color=c={color}:s=640x360:r=24',
                    '-t', '3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'mp4', str(root / member)],
                   check=True)
    group = Group(id=uid('group'), revision=uid('version'), name=f'模拟素材 · {scenario}',
                  members=[member], sizes=[(root / member).stat().st_size], closed=closed,
                  complete=closed, projection='rectilinear', scenario=scenario).model_dump()
    data['groups'].append(group)
    write(root, data)
    return group


def main():
    parser = argparse.ArgumentParser(description='创建固定标注的纯色模拟视频，不具备真实视觉内容')
    parser.add_argument('action', choices=['seed', 'add', 'disconnect', 'reconnect'])
    parser.add_argument('--scenario', choices=['materials', 'result', 'clear', 'occluded', 'uncertain', 'unrelated'], default='clear')
    parser.add_argument('--data-dir', default=os.getenv('BOLD_DATA_DIR', 'data'))
    args = parser.parse_args()
    root = Path(args.data_dir).resolve() / 'simulator'
    if args.action == 'seed':
        if (root / 'catalog.json').exists():
            print('模拟目录已存在，保留现有内容。')
            return
        for scenario in ('materials', 'result', 'unrelated'):
            add(root, scenario)
    elif args.action == 'add':
        add(root, args.scenario)
    else:
        path = root / 'catalog.json'
        if not path.exists():
            parser.error('先运行 seed')
        data = json.loads(path.read_text())
        data['connected'] = args.action == 'reconnect'
        write(root, data)
    print('模拟目录已更新；活动同步会话将在下一轮扫描发现变化。')


if __name__ == '__main__':
    main()
