from backend.app.schema import Shot, Evidence


def evaluate(shots: list[Shot], evidence: list[Evidence], confirmed: bool) -> dict:
    results, gaps = [], []
    for order, shot in enumerate(shots):
        relevant = [e for e in evidence if e.shot_id == shot.id]
        missing, support_ids, unresolved = [], [], []
        for criterion in shot.criteria:
            candidates = [e for e in relevant if e.criterion_id == criterion.id]
            support = [e for e in candidates if e.verdict == 'supports'
                       and (not criterion.continuous or e.continuous)]
            support_ids.extend(e.id for e in support)
            if criterion.required and not support:
                missing.append(criterion.description)
                unresolved.extend(candidates)
        state = 'covered'
        if missing:
            state = ('reshoot' if any(e.verdict == 'defect' for e in unresolved)
                     else 'uncertain' if unresolved else 'pending')
            gaps.append((not shot.required, not shot.critical, order, shot, missing, unresolved))
        results.append(dict(id=shot.id, title=shot.title, required=shot.required,
                            state=state, evidence_ids=support_ids, missing=missing))
    required = [r for r in results if r['required']]
    complete = confirmed and bool(required) and all(r['state'] == 'covered' for r in required)
    advice = None
    if gaps:
        _, _, _, shot, missing, unresolved = sorted(gaps, key=lambda g: g[:3])[0]
        defect = next((e.reason for e in unresolved if e.verdict == 'defect'), None)
        advice = dict(shot_id=shot.id, what=f'补拍：{shot.title}',
                      how=f'保持主体无遮挡，完整展示：{missing[0]}',
                      why=defect or f'尚无合格证据：{missing[0]}')
    return dict(shots=results, coverage_complete=complete, next_action=advice)
