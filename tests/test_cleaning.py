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
    assert cloud.calls[-1]['params']=={'did':'2.16','siid':2,'aiid':16,'in':['3,6']}

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
def test_x20_room_input_is_one_csv_string(client, rooms, expected):
    c, cloud = client
    c.start({'mode':'vacuum_mop'}, rooms)
    action = cloud.calls[-1]
    assert action['method'] == 'action'
    assert action['params']['in'] == [expected]
    assert len([call for call in cloud.calls if call['method']=='action']) == 1


def test_legacy_x20_rooms_use_same_wire_format():
    from mihome_cloud import MiHomeVacuum
    vacuum = MiHomeVacuum(Mock(), '1234567890', 'xiaomi.vacuum.d102gl', {})
    vacuum.rooms = Mock(return_value={})
    vacuum.run_action = Mock()
    vacuum.clean_rooms([4,6])
    vacuum.run_action.assert_called_once_with('clean_rooms', ['4,6'])
    vacuum.run_action.reset_mock()
    with pytest.raises(CleaningError):
        vacuum.clean_rooms([])
    vacuum.run_action.assert_not_called()
