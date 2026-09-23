import json
from urllib.error import HTTPError
from unittest.mock import Mock
import pytest
from backend.app.analysis.qwen import QwenModel
from backend.app.config import Settings
from backend.app.schema import DomainError


def test_invalid_json_truncation_and_http_errors_never_expose_key(tmp_path):
    model = QwenModel(Settings(data_dir=tmp_path, model_api_key='local-test-secret'))
    response = Mock()
    model.opener.open = Mock(return_value=response)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    for content, finish in [('not json', 'stop'), ('{}', 'length')]:
        response.read.return_value = json.dumps({'choices': [{'finish_reason': finish,
            'message': {'content': content}}]}).encode()
        with pytest.raises(DomainError) as error:
            model.complete('goal', 'JSON')
        assert error.value.code == 'MODEL_OUTPUT_INVALID'
        assert 'local-test-secret' not in str(error.value)
    model.opener.open.side_effect = HTTPError('https://example.invalid', 401, 'local-test-secret', {}, None)
    with pytest.raises(DomainError) as error:
        model.complete('goal', 'JSON')
    assert error.value.code == 'CAPABILITY_UNVERIFIED'
    assert 'local-test-secret' not in str(error.value)


def test_video_evidence_rejects_wrong_ids_and_out_of_range_times(tmp_path, monkeypatch):
    model = QwenModel(Settings(data_dir=tmp_path))
    source = tmp_path / 'video.mp4'
    source.write_bytes(b'fixture')
    rendition = dict(id='r1', path=str(source), duration=2)
    shots = [dict(id='s1', criteria=[dict(id='c1')])]
    item = dict(shot_id='s1', criterion_id='c1', start=0, end=3, verdict='supports', reason='visible', continuous=False)
    monkeypatch.setattr(model, 'complete', lambda *args: ({'evidence': [item]}, {}))
    with pytest.raises(DomainError) as error:
        model.observe(shots, 'clip1', rendition)
    assert error.value.code == 'MODEL_OUTPUT_INVALID'
    item.update(end=1, criterion_id='wrong')
    with pytest.raises(DomainError):
        model.observe(shots, 'clip1', rendition)


def test_video_upload_is_same_rendition_and_ids_are_assigned_locally(tmp_path, monkeypatch):
    model = QwenModel(Settings(data_dir=tmp_path))
    source = tmp_path / 'video.mp4'
    source.write_bytes(b'content')
    captured = []
    def complete(content, instruction):
        captured.append(content)
        return {'evidence': [dict(shot_id='s1', criterion_id='c1', start=0, end=1,
            verdict='uncertain', reason='动作太快无法确认', continuous=False)]}, {}
    monkeypatch.setattr(model, 'complete', complete)
    items, record = model.observe([dict(id='s1', criteria=[dict(id='c1')])], 'clip1',
                                 dict(id='r1', path=str(source), duration=2))
    assert captured[0][0]['video_url']['url'] == 'data:video/mp4;base64,Y29udGVudA=='
    assert items[0]['rendition_id'] == 'r1' and items[0]['clip_id'] == 'clip1'
    assert items[0]['id'].startswith('evidence_')
    assert record['rendition_id'] == 'r1'


def test_config_file_does_not_execute_shell_and_secret_not_in_repr(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('DASHSCOPE_API_KEY=local-secret\nBOLD_MODEL_NAME=qwen3-vl-flash\n')
    monkeypatch.setenv('BOLD_ENV_FILE', str(env))
    monkeypatch.delenv('DASHSCOPE_API_KEY', raising=False)
    settings = Settings.from_env()
    assert settings.model_api_key == 'local-secret'
    assert 'local-secret' not in repr(settings)


def test_plan_assigns_resource_ids_locally(tmp_path, monkeypatch):
    model = QwenModel(Settings(data_dir=tmp_path))
    output = {'shots': [{'title': '展示工具', 'required': True, 'critical': False,
                         'criteria': [{'description': '工具清晰可见', 'required': True, 'continuous': False}]},
                        {'title': '执行操作', 'required': True, 'critical': True,
                         'criteria': [{'description': '动作连续可见', 'required': True, 'continuous': True}]}]}
    monkeypatch.setattr(model, 'complete', lambda *args: (output, {'model': 'fixture'}))
    shots, _ = model.plan('测试', '', 30)
    ids = [shot['id'] for shot in shots] + [criterion['id'] for shot in shots for criterion in shot['criteria']]
    assert len(ids) == len(set(ids))
    assert all(identifier.startswith(('shot_', 'criterion_')) for identifier in ids)


def test_plan_does_not_assume_every_goal_is_a_tutorial(tmp_path, monkeypatch):
    model = QwenModel(Settings(data_dir=tmp_path))
    captured = {}
    output = {'shots': [{'title': '环境与氛围', 'required': True, 'critical': False,
                         'criteria': [{'description': '咖啡馆环境和顾客活动清晰可见',
                                       'required': True, 'continuous': False}]}]}

    def complete(content, instruction):
        captured['content'] = json.loads(content)
        captured['instruction'] = instruction
        return output, {'model': 'fixture'}

    monkeypatch.setattr(model, 'complete', complete)
    model.plan('展示一家咖啡馆的环境和招牌饮品', '手持拍摄', 45)

    assert captured['content']['goal'] == '展示一家咖啡馆的环境和招牌饮品'
    assert '不要默认视频是教程' in captured['instruction']
    assert '只有目标确实涉及教学或操作演示时' in captured['instruction']
    assert '清单用于检查素材覆盖，不是剪辑时间线' in captured['instruction']
