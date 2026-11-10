"""Explicit X20 Pro cleaning plans. Reads never write; writes never reauthenticate/retry.

Enums and action IDs: Xiaomi MIoT xiaomi.vacuum.d102gl specification.
Settings persist on the device. A multi-property write is not a transaction.
"""
from __future__ import annotations

from .maps import MODEL

# name: (SIID, PIID, raw -> semantic value)
SETTINGS = {
    'mode': (2, 4, {1: 'vacuum', 2: 'mop', 3: 'vacuum_mop', 4: 'vacuum_then_mop'}),
    'suction': (2, 9, {1: 'quiet', 2: 'standard', 3: 'strong', 4: 'turbo'}),
    'water': (2, 10, {0: 'off', 1: 'low', 2: 'medium', 3: 'high'}),
    'mop_wetness': (2, 60, {0: 'daily', 1: 'deep'}),
    'passes': (2, 8, {1: 'once', 2: 'twice', 3: 'three_times'}),
    'route': (2, 74, {1: 'quick', 2: 'standard', 3: 'careful'}),
    'obstacles': (2, 75, {0: 'gentle', 1: 'coverage'}),
}
TELEMETRY = {'status': (2, 2), 'fault': (2, 3), 'battery': (3, 1),
             'area': (2, 6), 'time': (2, 7), 'mode': (2, 4), 'scope': (2, 5)}
COMMANDS = {'pause': (2, 7), 'resume': (2, 8), 'stop': (2, 2), 'dock': (3, 1)}


class CleaningError(ValueError):
    """Payload-free, stable reason; never includes provider responses."""


def encode_room_ids(room_ids: list[int]) -> str:
    """d102gl action 2/16 takes one CSV string (MIoT input property 2/15).

    Nested arrays can receive code 0 without causing any cleaning. Empty input
    must never be treated as a whole-home request.
    """
    if (not isinstance(room_ids, list) or not 1 <= len(room_ids) <= 64
            or any(type(r) is not int or r <= 0 for r in room_ids)
            or len(set(room_ids)) != len(room_ids)):
        raise CleaningError('invalid_rooms')
    return ','.join(str(r) for r in room_ids)


class X20CleaningClient:
    def __init__(self, cloud, device_id: str, model: str = MODEL):
        if model != MODEL or not str(device_id).isdigit():
            raise CleaningError('unsupported_model')
        self.cloud, self.did = cloud, str(device_id)

    def _rpc(self, method, params):
        # No automatic replay, even for a service-token rejection after a write.
        try:
            result = self.cloud._rpc(self.cloud._base_url + '/v2/home/rpc/' + self.did,
                                     {'method': method, 'params': params}, allow_reauth=False)
        except Exception:
            raise CleaningError('cloud_outcome_unknown') from None
        if not isinstance(result, dict) or result.get('code') != 0:
            raise CleaningError('cloud_rejected')
        return result.get('result')

    def read(self):
        pairs = sorted({v[:2] for v in SETTINGS.values()} | set(TELEMETRY.values()))
        result = self._rpc('get_properties', [dict(did=f'{s}.{p}', siid=s, piid=p) for s,p in pairs])
        if not isinstance(result, list):
            raise CleaningError('invalid_telemetry')
        values = {(v.get('siid'), v.get('piid')): v.get('value') for v in result
                  if isinstance(v, dict) and v.get('code') == 0}
        options = {}
        for name,(s,p,choices) in SETTINGS.items():
            raw = values.get((s,p))
            # Unknown values/unsupported properties cannot silently acquire defaults.
            available = type(raw) is int and raw in choices
            options[name] = {'available': available, 'choices': list(choices.values()) if available else [],
                             'value': choices.get(raw) if available else None}
        return {'options': options, 'telemetry': {name: values.get(pair) for name,pair in TELEMETRY.items()}}

    def _action(self, siid, aiid, params, before_write):
        if before_write: before_write()
        result = self._rpc('action', {'did': f'{siid}.{aiid}', 'siid': siid, 'aiid': aiid, 'in': params})
        if not isinstance(result, dict) or result.get('code') != 0:
            raise CleaningError('action_rejected')
        return {'status': 'ok'}

    def command(self, command, *, before_write=None):
        if command not in COMMANDS:
            raise CleaningError('invalid_command')
        return self._action(*COMMANDS[command], [], before_write)

    def start(self, settings: dict[str, str], room_ids: list[int] | None = None, *, before_write=None):
        """Apply a validated draft, verify readback, then send exactly one start.

        None means whole home. An empty room list is never whole home. The caller
        must additionally bind selected IDs to a freshly read active map.
        A failed settings write/readback may leave settings changed; never retry
        automatically and never continue to the start action after such a failure.
        """
        if not isinstance(settings, dict) or 'mode' not in settings or any(
            name not in SETTINGS or not isinstance(value, str) or value not in SETTINGS[name][2].values()
            for name,value in settings.items()
        ):
            raise CleaningError('invalid_settings')
        room_param = encode_room_ids(room_ids) if room_ids is not None else None
        current = self.read()
        if type(current['telemetry']['status']) is not int or current['telemetry']['status'] not in (1, 2, 9):
            raise CleaningError('robot_not_idle')
        if any(not current['options'][key]['available'] for key in settings):
            raise CleaningError('setting_unavailable')
        params = []
        for name,value in settings.items():
            s,p,choices = SETTINGS[name]
            params.append(dict(did=f'{s}.{p}',siid=s,piid=p,value=next(k for k,v in choices.items() if v==value)))
        if room_ids is None:
            if type(current['telemetry']['scope']) is not int or current['telemetry']['scope'] not in range(1, 8):
                raise CleaningError('setting_unavailable')
            params.append(dict(did='2.5', siid=2, piid=5, value=1))
        if before_write: before_write()
        result = self._rpc('set_properties', params)
        if not isinstance(result, list) or len(result) != len(params):
            raise CleaningError('settings_partially_applied')
        acknowledgements = {(v.get('siid'),v.get('piid')):v.get('code') for v in result if isinstance(v,dict)}
        if any(acknowledgements.get((v['siid'],v['piid'])) != 0 for v in params):
            raise CleaningError('settings_partially_applied')
        verified = self.read()
        if any(verified['options'][key]['value'] != value for key,value in settings.items()):
            raise CleaningError('settings_not_confirmed')
        if room_ids is None and verified['telemetry']['scope'] != 1:
            raise CleaningError('settings_not_confirmed')
        if type(verified['telemetry']['status']) is not int or verified['telemetry']['status'] not in (1,2,9):
            raise CleaningError('settings_applied_robot_changed')
        # Generic start honours the selected program; start_sweep_mop would select a mode.
        try:
            return self._action(2, 16 if room_ids is not None else 1,
                                [room_param] if room_param is not None else [], before_write)
        except Exception:
            # Settings already changed; even a revoked guard is not a no-effect rejection.
            raise CleaningError('settings_applied_start_not_confirmed') from None
