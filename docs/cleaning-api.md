# X20 Pro cleaning API

`MiHomeVacuum.cleaning` is an opt-in `X20CleaningClient` for
`xiaomi.vacuum.d102gl`. It uses the existing `MiHomeCloud` connection directly,
without another vacuum dependency or login mechanism. Requires mihome-cloud 0.4.3 for diagnostic error attributes.

```python
# vacuum is an existing authenticated MiHomeVacuum instance.
settings = vacuum.cleaning.read()  # read-only
options = settings['options']     # available, choices and current value per field
status = settings['telemetry']
```

Unsupported/unrecognized property values are marked unavailable. Do not invent
fallback defaults or offer writes for unavailable fields. Choices come from the
model's public MIoT specification; a readable value does not prove every write
combination works on every firmware.

The following calls **change the robot**. Invoke them only after an explicit
user command; do not run them merely to preview a plan:

```python
snapshot = vacuum.maps.get_snapshot(allow_stale=False)
known_ids = {room['room_id'] for room in snapshot.to_dict()['rooms']}
selected_ids = [room_id for room_id in requested_room_ids if room_id in known_ids]
if not selected_ids or len(selected_ids) != len(requested_room_ids):
    raise ValueError('Review the room selection against the active map')

vacuum.cleaning.start(
    {'mode': 'vacuum_mop', 'suction': 'standard', 'route': 'careful',
     'mop_wetness': 'daily', 'passes': 'once'},
    room_ids=selected_ids,
)
# room_ids=None explicitly means the whole active map; [] is rejected.
# Other explicit commands:
vacuum.cleaning.command('pause')   # also resume, stop, dock
```

| Setting | Choices | MIoT service/property |
| --- | --- | --- |
| `mode` | `vacuum`, `mop`, `vacuum_mop`, `vacuum_then_mop` | 2/4 (1–4) |
| `suction` | `quiet`, `standard`, `strong`, `turbo` | 2/9 (1–4) |
| `water` | `off`, `low`, `medium`, `high` | 2/10 (0–3) |
| `mop_wetness` | `daily`, `deep` | 2/60 (0–1) |
| `passes` | `once`, `twice`, `three_times` | 2/8 (1–3) |
| `route` | `quick`, `standard`, `careful` | 2/74 (1–3) |
| `obstacles` | `gentle`, `coverage` | 2/75 (0–1) |

The client uses `get_properties`, `set_properties` and `action` through
`/v2/home/rpc/{did}`. A start checks idle/charging status, validates the complete
plan, writes settings once, checks all acknowledgements and reads values back
before issuing one start action. Whole-home plans also set/read back sweep scope
2/5 to Global (1). The start actions are 2/1 (generic whole-home start) and 2/16
(selected rooms, input property 15 tagged with a CSV string, such as
`[{"piid":15,"value":"4,6"}]`). Pause/resume/stop are 2/7, 2/8, 2/2; dock is
3/1. `before_write=` optionally revalidates caller authorization before each write.

Settings persist on the robot. Applying them is not transactional: a rejected
batch, readback failure, revoked authorization or failed start can leave some
settings changed. `CleaningError` contains a payload-free reason, an optional `stage`
(`get_properties`, `set_properties`, `action`, `start_guard`) and a numeric
`api_code` when the provider returned one. These diagnostics never include raw
responses, device identifiers, selected rooms or credentials. Do not retry
writes automatically, including on a timeout, lost response or expired session.
Read status and ask the operator to assess the outcome. Successful acknowledgement
means the command was accepted, not that cleaning completed. Reads/writes on this
client use `allow_reauth=False`; ordinary session recovery belongs to the host.

A read-only probe against the tested X20 Pro returned recognized values for all
seven exposed settings. The transport contract and all four modes are tested
with synthetic cloud responses. **The new plan flow has not been physically tested for every mode or
setting combination.** Actual map downloads, active routes/positions and prior
room cleaning are separate device evidence. Historical routes, map switching,
carpet rules, schedules and station-maintenance settings are outside this API.

Source: [Xiaomi MIoT specification for d102gl](https://miot-spec.org/miot-spec-v2/instance?type=urn:miot-spec-v2:device:vacuum:0000A006:xiaomi-d102gl:1).

### Room-start wire format and verification status

X20 Pro input property 2/15 is a string. The direct device RPC currently sends
`in: [{"piid":15,"value":"4,6"}]` (since 0.4.2), following the tagged-input
finding in the [X20 Pro protocol investigation](https://github.com/AldenDana/ha-xiaomi-vacuum-x20pro/blob/master/docs/METHOD.md).
The high-level Home Assistant cloud action service accepts a bare CSV string;
that service uses `/miotspec/action`, whereas this client uses the direct RPC.
These are different transport contracts.

Physical execution of this flow is **not yet verified on our test robot**.
Earlier nested-array and untagged-CSV attempts returned acknowledgements without
observed movement. A tagged-input attempt ended with an unknown outcome after
settings changed; no successful start was observed. Version 0.4.3 adds stage and
numeric error diagnostics so the next operator-triggered attempt can identify
whether settings, readback or the action failed. It does not change the command
sequence or replay failed commands. The reference's separate room-configuration
action (2/13) is not implemented by this cleaning-plan API.
