from backend.app.schema import Shot, Criterion, Evidence, DomainError
from backend.app.storage.repository import uid


def plan(goal):
    return [Shot(id=uid('shot'), title=title, critical=i == 1, criteria=[
        Criterion(id=uid('criterion'), description=description, continuous=i == 1)
    ]).model_dump() for i, (title, description) in enumerate([
        ('准备材料与工具', f'清晰展示「{goal[:80]}」所需材料与工具'),
        ('展示关键操作', '连续展示完整操作过程，关键连接或操作位置无遮挡'),
        ('展示完成效果', '清晰展示完成后的结果及可见检查')])]


def observe(shots, clip_id, rendition, scenario):
    # Scripted fixture answers. No visual inference takes place here.
    index = {'materials': 0, 'occluded': 1, 'clear': 1, 'uncertain': 1, 'result': 2}.get(scenario)
    if index is None or index >= len(shots):
        return []
    shot = shots[index]
    verdict = 'defect' if scenario == 'occluded' else 'uncertain' if scenario == 'uncertain' else 'supports'
    return [Evidence(id=uid('evidence'), shot_id=shot['id'], criterion_id=c['id'], clip_id=clip_id,
                     rendition_id=rendition['id'], start=0, end=min(2, rendition['duration']),
                     verdict=verdict, continuous=scenario == 'clear',
                     reason='模拟标注：手遮挡关键操作' if verdict == 'defect' else '模拟标注：' + scenario
                     ).model_dump() for c in shot['criteria']]


def validate_evidence(items, shots, clip_id, renditions):
    valid = {(s['id'], c['id']) for s in shots for c in s['criteria']}
    durations = {r['id']: r['duration'] for r in renditions}
    checked, ids = [], set()
    for raw in items:
        try:
            e = Evidence.model_validate(raw)
        except ValueError as exc:
            raise DomainError('MODEL_OUTPUT_INVALID', '模型证据格式无效', 422) from exc
        if ((e.shot_id, e.criterion_id) not in valid or e.clip_id != clip_id
                or e.rendition_id not in durations or e.end > durations[e.rendition_id] or e.id in ids):
            raise DomainError('MODEL_OUTPUT_INVALID', '模型引用了错误 ID 或越界时间', 422)
        ids.add(e.id)
        checked.append(e.model_dump())
    return checked
