from unittest.mock import Mock
import pytest
from mihome_cloud.cleaning import X20CleaningClient, CleaningError, SETTINGS

class Cloud:
    _base_url='https://example.invalid/app'
    def __init__(self):
        self.calls=[];self.values={(s,p):next(iter(c)) for s,p,c in SETTINGS.values()}
        self.values.update({(2,5):2,(2,2):2,(2,3):0,(3,1):80,(2,6):0,(2,7):0})
        self.reject=False;self.drop=False;self.ignore=False
    def _rpc(self,url,body,*,allow_reauth):
        assert allow_reauth is False
        self.calls.append(body)
        method,params=body['method'],body['params']
        if method=='get_properties':
            return {'code':0,'result':[{**p,'code':0 if (p['siid'],p['piid']) in self.values else -1,'value':self.values.get((p['siid'],p['piid']))} for p in params]}
        if method=='set_properties':
            if self.drop:raise TimeoutError('private request')
            if not self.ignore:
                self.values.update({(p['siid'],p['piid']):p['value'] for p in params})
            return {'code':0,'result':[{**p,'code':-1 if self.reject else 0} for p in params]}
        return {'code':0,'result':{'code':0}}

@pytest.fixture
def client():
    cloud=Cloud();return X20CleaningClient(cloud,'1234567890'),cloud

def test_read_never_writes_and_unknown_values_unavailable(client):
    c,cloud=client;cloud.values[(2,74)]=99
    result=c.read()
    assert result['options']['route']['available'] is False
    assert result['options']['mode']['choices']==['vacuum','mop','vacuum_mop','vacuum_then_mop']
    assert all(r['method']=='get_properties' for r in cloud.calls)

@pytest.mark.parametrize('settings,rooms', [({'mode':'invalid'},None),({'mode':'vacuum','unknown':'value'},None),({'mode':'vacuum'},[]),({'mode':'vacuum'},[True]),({'mode':'vacuum'},[1,1])])
def test_invalid_draft_has_no_effects(client,settings,rooms):
    c,cloud=client
    with pytest.raises(CleaningError):c.start(settings,rooms)
    assert not cloud.calls

@pytest.mark.parametrize('mode,raw', [('vacuum',1),('mop',2),('vacuum_mop',3),('vacuum_then_mop',4)])
def test_modes_readback_before_one_start(client,mode,raw):
    c,cloud=client
    c.start({'mode':mode,'passes':'twice'},[3,6])
    assert cloud.values[(2,4)]==raw
    assert [r['method'] for r in cloud.calls]==['get_properties','set_properties','get_properties','action']
    assert cloud.calls[-1]['params']=={'did':'2.16','siid':2,'aiid':16,'in':[{'piid':15,'value':'3,6'}]}

def test_whole_home_uses_generic_start(client):
    c,cloud=client;c.start({'mode':'vacuum_then_mop'})
    assert cloud.calls[-1]['params']['aiid']==1
    assert cloud.values[(2,5)]==1

@pytest.mark.parametrize('failure',['reject','drop','ignore'])
def test_partial_write_or_unknown_transport_never_starts_or_retries(client,failure):
    c,cloud=client;setattr(cloud,failure,True)
    with pytest.raises(CleaningError):c.start({'mode':'mop'})
    assert sum(r['method']=='set_properties' for r in cloud.calls)==1
    assert all(r['method']!='action' for r in cloud.calls)

def test_busy_and_unsupported_settings_never_write(client):
    c,cloud=client;cloud.values[(2,2)]=4
    with pytest.raises(CleaningError):c.start({'mode':'vacuum'})
    cloud.values[(2,2)]=2;del cloud.values[(2,74)]
    with pytest.raises(CleaningError):c.start({'mode':'vacuum','route':'careful'})
    assert all(r['method']=='get_properties' for r in cloud.calls)

def test_guard_revocation_before_settings(client):
    c,cloud=client
    with pytest.raises(RuntimeError):c.start({'mode':'vacuum'},before_write=Mock(side_effect=RuntimeError()))
    assert all(r['method']=='get_properties' for r in cloud.calls)

@pytest.mark.parametrize('command,ids',[('pause',(2,7)),('resume',(2,8)),('stop',(2,2)),('dock',(3,1))])
def test_transport_controls_exactly_once(client,command,ids):
    c,cloud=client;c.command(command)
    assert len(cloud.calls)==1
    p=cloud.calls[0]['params'];assert (p['siid'],p['aiid'])==ids


def test_revoked_after_settings_reports_partial_effects(client):
    c, cloud = client
    guard = Mock(side_effect=[None, RuntimeError('revoked')])
    with pytest.raises(CleaningError, match='settings_applied_start_not_confirmed'):
        c.start({'mode':'mop'}, before_write=guard)
    assert cloud.values[(2,4)] == 2
    assert all(call['method'] != 'action' for call in cloud.calls)


@pytest.mark.parametrize('rooms,expected', [([4], '4'), ([6,3], '6,3')])
def test_x20_room_rpc_input_tags_spec_property_15_with_csv_string(client, rooms, expected):
    c, cloud = client
    c.start({'mode':'vacuum_mop'}, rooms)
    action = cloud.calls[-1]
    assert action['method'] == 'action'
    assert action['params']['in'] == [{'piid':15,'value':expected}]
    assert len([call for call in cloud.calls if call['method']=='action']) == 1


def test_legacy_x20_rooms_use_same_wire_format():
    from mihome_cloud import MiHomeVacuum
    vacuum = MiHomeVacuum(Mock(), '1234567890', 'xiaomi.vacuum.d102gl', {})
    vacuum.rooms = Mock(return_value={})
    vacuum.run_action = Mock()
    vacuum.clean_rooms([4,6])
    vacuum.run_action.assert_called_once_with('clean_rooms', [{'piid':15,'value':'4,6'}])
    vacuum.run_action.reset_mock()
    with pytest.raises(CleaningError):
        vacuum.clean_rooms([])
    vacuum.run_action.assert_not_called()


def test_legacy_room_payload_reaches_rpc_with_tagged_string():
    # Exercise real profile resolution and cloud.action serialization, rather
    # than accepting a high-level shorthand as if it were a device payload.
    from mihome_cloud import MiHomeCloud, MiHomeVacuum
    cloud = MiHomeCloud('', '', country='de')
    cloud._rpc = Mock(return_value={'code':0, 'result':{'code':0}})
    from mihome_cloud.profiles import load_profile
    model = 'xiaomi.vacuum.d102gl'
    vacuum = MiHomeVacuum(cloud, '1234567890', model, load_profile(model))
    vacuum.rooms = Mock(return_value={})
    vacuum.clean_rooms([4])
    args, _ = cloud._rpc.call_args
    assert args[0].endswith('/v2/home/rpc/1234567890')
    assert args[1] == {'method':'action', 'params':{
        'did':'2.16', 'siid':2, 'aiid':16,
        'in':[{'piid':15, 'value':'4'}]}}
    assert cloud._rpc.call_count == 1


@pytest.mark.parametrize('outer', [False, True])
def test_start_diagnostics_preserve_only_stage_and_numeric_error_code(client, outer):
    c, cloud = client
    original = cloud._rpc
    def fail_action(url, body, **kwargs):
        if body['method'] == 'action':
            cloud.calls.append(body)
            error = {'code': -704030001, 'message': 'PRIVATE_DEVICE_PAYLOAD'}
            return error if outer else {'code': 0, 'result': error}
        return original(url, body, **kwargs)
    cloud._rpc = fail_action
    with pytest.raises(CleaningError) as caught:
        c.start({'mode': 'vacuum_mop'}, [3,4])
    error = caught.value
    assert str(error) == 'settings_applied_start_not_confirmed'
    assert error.stage == 'action' and error.api_code == -704030001
    assert 'PRIVATE' not in repr(error) and 'PRIVATE' not in repr(vars(error))
    assert sum(call['method'] == 'action' for call in cloud.calls) == 1


def test_error_diagnostics_discard_non_numeric_provider_codes():
    error = CleaningError('cloud_rejected', stage='action', api_code='PRIVATE_PAYLOAD')
    assert error.api_code is None


def test_start_during_drying_does_not_send_hidden_stop(client):
    c, cloud = client
    cloud.values.update({(2,2):14, (2,18):'{"mode":1,"runtime":0}'})
    state = c.read()
    assert state['controls'] == {'can_start':True, 'can_end_drying':True}
    assert state['telemetry']['station_operation'] == 'drying'
    cloud.calls.clear()
    c.start({'mode':'vacuum_mop'}, [4])
    assert [x['method'] for x in cloud.calls] == ['get_properties','set_properties','get_properties','action']
    assert cloud.calls[-1]['params']['aiid'] == 16


@pytest.mark.parametrize('raw', [None, '', 'not JSON', '{}', '[]', '{"mode":true}', '{"mode":"1"}', '{"mode":2}', '{"mode":3}', '{"mode":99}'])
def test_unknown_or_washing_station_cannot_unlock_start(client, raw):
    c, cloud = client;cloud.values.update({(2,2):14, (2,18):raw})
    assert c.read()['controls'] == {'can_start':False, 'can_end_drying':False}
    with pytest.raises(CleaningError, match='robot_not_idle'):c.start({'mode':'vacuum'}, [4])
    assert all(x['method']=='get_properties' for x in cloud.calls)


def test_drying_change_during_settings_prevents_start(client):
    c, cloud = client;cloud.values.update({(2,2):14, (2,18):'{"mode":1}'})
    original = cloud._rpc
    def change(url, body, **kwargs):
        result = original(url, body, **kwargs)
        if body['method']=='set_properties':cloud.values[(2,18)]='{"mode":3}'
        return result
    cloud._rpc=change
    with pytest.raises(CleaningError, match='settings_applied_robot_changed'):c.start({'mode':'vacuum'}, [4])
    assert all(x['method']!='action' for x in cloud.calls)


def test_end_drying_uses_its_own_action_once(client):
    c, cloud = client;cloud.values.update({(2,2):14, (2,18):'{"mode":1}'})
    guard=Mock();c.command('end_drying', before_write=guard)
    assert [x['method'] for x in cloud.calls]==['get_properties','action']
    assert cloud.calls[-1]['params']=={'did':'2.32','siid':2,'aiid':32,'in':[]}
    guard.assert_called_once()


def test_end_drying_is_not_a_general_stop(client):
    c, cloud=client;cloud.values.update({(2,2):4, (2,18):'{"mode":0}'})
    with pytest.raises(CleaningError, match='station_not_drying'):c.command('end_drying')
    assert all(x['method']=='get_properties' for x in cloud.calls)
