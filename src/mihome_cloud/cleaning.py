"""Explicit X20 Pro cleaning plans. Reads never write; writes never reauthenticate/retry.

Enums and action IDs: Xiaomi MIoT xiaomi.vacuum.d102gl specification.
Settings persist on the device. A multi-property write is not a transaction.
"""
from __future__ import annotations

import json

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
COMMANDS = {'pause': (2, 7), 'resume': (2, 8), 'stop': (2, 2), 'dock': (3, 1), 'end_drying': (2, 32)}


class CleaningError(ValueError):
    """Payload-free reason and optional protocol diagnostics; no provider bodies."""

    def __init__(self, reason, *, stage=None, api_code=None):
        super().__init__(reason)
        self.stage = stage if stage in {'get_properties', 'set_properties', 'action', 'start_guard'} else None
        self.api_code = api_code if type(api_code) is int else None


def station_telemetry(raw):
    """Observed d102gl modes only; malformed/unknown data never means idle."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = None
    mode = raw.get('mode') if isinstance(raw, dict) else None
    if type(mode) is not int:
        mode = None
    return {'station_mode': mode,
            'station_operation': {0: 'idle', 1: 'drying', 3: 'washing_mops'}.get(mode)}


def is_drying(telemetry):
    return (type(telemetry.get('status')) is int and telemetry['status'] == 14
            and type(telemetry.get('station_mode')) is int and telemetry['station_mode'] == 1)


def can_start_cleaning(telemetry):
    return ((type(telemetry.get('status')) is int and telemetry['status'] in (1, 2, 9))
            or is_drying(telemetry))


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


def room_action_inputs(room_ids: list[int]) -> list[dict]:
    """RPC action inputs must identify the spec's string property 2/15.

    A bare CSV string is the high-level /miotspec/action convention. This
    library uses /v2/home/rpc/{did}, which forwards the device wire payload.
    d102gl can acknowledge untagged inputs without executing the action.
    """
    return [{'piid': 15, 'value': encode_room_ids(room_ids)}]


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
            raise CleaningError('cloud_outcome_unknown', stage=method) from None
        if not isinstance(result, dict) or result.get('code') != 0:
            raise CleaningError('cloud_rejected', stage=method,
                                api_code=result.get('code') if isinstance(result, dict) else None)
        return result.get('result')

    def read(self):
        pairs = sorted({v[:2] for v in SETTINGS.values()} | set(TELEMETRY.values()) | {(2, 18)})
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
        telemetry = {name: values.get(pair) for name,pair in TELEMETRY.items()}
        telemetry.update(station_telemetry(values.get((2, 18))))
        return {'options': options, 'telemetry': telemetry,
                'controls': {'can_start': can_start_cleaning(telemetry),
                             'can_end_drying': is_drying(telemetry)}}

    def _action(self, siid, aiid, params, before_write):
        if before_write: before_write()
        result = self._rpc('action', {'did': f'{siid}.{aiid}', 'siid': siid, 'aiid': aiid, 'in': params})
        if not isinstance(result, dict) or result.get('code') != 0:
            raise CleaningError('action_rejected', stage='action',
                                api_code=result.get('code') if isinstance(result, dict) else None)
        return {'status': 'ok'}

    def command(self, command, *, before_write=None):
        if command not in COMMANDS:
            raise CleaningError('invalid_command')
        if command == 'end_drying' and not is_drying(self.read()['telemetry']):
            raise CleaningError('station_not_drying')
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
        room_inputs = room_action_inputs(room_ids) if room_ids is not None else []
        current = self.read()
        if not can_start_cleaning(current['telemetry']):
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
            raise CleaningError('settings_partially_applied', stage='set_properties')
        acknowledgements = {(v.get('siid'),v.get('piid')):v.get('code') for v in result if isinstance(v,dict)}
        failed = [acknowledgements.get((v['siid'],v['piid'])) for v in params
                  if acknowledgements.get((v['siid'],v['piid'])) != 0]
        if failed:
            raise CleaningError('settings_partially_applied', stage='set_properties', api_code=failed[0])
        verified = self.read()
        if any(verified['options'][key]['value'] != value for key,value in settings.items()):
            raise CleaningError('settings_not_confirmed', stage='get_properties')
        if room_ids is None and verified['telemetry']['scope'] != 1:
            raise CleaningError('settings_not_confirmed', stage='get_properties')
        if not can_start_cleaning(verified['telemetry']):
            raise CleaningError('settings_applied_robot_changed')
        # Generic start honours the selected program; start_sweep_mop would select a mode.
        try:
            return self._action(2, 16 if room_ids is not None else 1,
                                room_inputs, before_write)
        except Exception as exc:
            # Settings already changed; even a revoked guard is not a no-effect rejection.
            raise CleaningError('settings_applied_start_not_confirmed',
                                stage=exc.stage if isinstance(exc, CleaningError) else 'start_guard',
                                api_code=exc.api_code if isinstance(exc, CleaningError) else None) from None
