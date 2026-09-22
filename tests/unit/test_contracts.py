import pytest
from pydantic import ValidationError
from backend.app.schema import Evidence, PlanEdit, DomainError
from backend.app.analysis.simulator import validate_evidence, plan


def test_AI05_invalid_ids_time_and_enum():
    fields = dict(id='e', shot_id='s', criterion_id='k', clip_id='c', rendition_id='r',
                  start=0, end=1, verdict='supports', reason='visible')
    for change in ({'start': -1}, {'end': 0}, {'verdict': 'complete'}, {'clip_id': '../file'}, {'end': float('nan')}):
        with pytest.raises(ValidationError):
            Evidence(**(fields | change))
    with pytest.raises(DomainError):
        validate_evidence([fields], plan('测试'), 'c', [{'id': 'r', 'duration': 2}])


def test_AI01_duplicate_criteria_and_empty_plan_rejected():
    with pytest.raises(ValidationError):
        PlanEdit(expected_revision=0, shots=[])
    shots = plan('测试')
    shots[1]['criteria'][0]['id'] = shots[0]['criteria'][0]['id']
    with pytest.raises(ValidationError):
        PlanEdit(expected_revision=0, shots=shots)
