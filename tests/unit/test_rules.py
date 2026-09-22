from backend.app.schema import Criterion, Shot, Evidence
from backend.app.coverage.rules import evaluate


def shot():
    return Shot(id='s1', title='安装', criteria=[Criterion(id='k1', description='连续展示连接动作', continuous=True)])


def evidence(**kw):
    return Evidence(**dict(id='e1', shot_id='s1', criterion_id='k1', clip_id='c1', rendition_id='r1',
                          start=0, end=2, verdict='supports', reason='连接可见', continuous=True) | kw)


def test_RU01_empty_and_unconfirmed():
    assert not evaluate([], [], True)['coverage_complete']
    assert not evaluate([shot()], [evidence()], False)['coverage_complete']


def test_RU02_good_evidence_survives_bad_clip():
    result = evaluate([shot()], [evidence(), evidence(id='e2', verdict='defect')], True)
    assert result['coverage_complete']
    assert result['next_action'] is None


def test_AI04_continuity_cannot_be_assembled_from_stills():
    result = evaluate([shot()], [evidence(continuous=False)], True)
    assert not result['coverage_complete']
    assert result['shots'][0]['state'] == 'uncertain'


def test_RU08_advice_and_defect():
    result = evaluate([shot()], [evidence(verdict='defect', reason='手遮挡连接处')], True)
    assert result['shots'][0]['state'] == 'reshoot'
    assert result['next_action']['why'] == '手遮挡连接处'
