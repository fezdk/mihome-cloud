# X20 Pro cleaning API

`MiHomeVacuum.cleaning` is an opt-in `X20CleaningClient` for
`xiaomi.vacuum.d102gl`. It uses the existing `MiHomeCloud` connection directly,
without another vacuum dependency or login mechanism. Requires mihome-cloud 0.4.4 for station-aware start and drying controls.

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
plan (idle/charging or observed status 14 with station mode 1), writes settings once, checks all acknowledgements and reads values back
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

A user-triggered production run with 0.4.3 **confirmed a two-room vacuum-and-mop
start**: the receipt was accepted, `current_cleaning_config` (2/40) contained
exactly the selected room IDs with `clean_mode:3`, counters reset, and status
changed from Charging (2) to GoWash (7). The operator simultaneously saw
"Cleaning the mop" in Xiaomi Home; station JSON reported `mode:3`. The robot subsequently reported Cleaning (4), station mode reset to 0, and the
operator saw "Cleaning" in the app. This verifies room-plan acceptance and entry
into cleaning, not every setting combination or eventual task completion. See [station observations](x20-pro-station-observations.md).

Earlier nested-array and untagged-CSV attempts returned acknowledgements without
observed movement. An earlier tagged-input attempt ended with an unknown outcome
after settings changed. Its exact failure stage was not retained, so the cause
remains unknown. Version 0.4.3 adds stage/numeric error diagnostics; it did not
change the 0.4.2 command sequence. Do not attribute success to diagnostics or claim
that tagged inputs alone explain every earlier failure. The successful run used
one explicit operator Start, no automatic retry, and no separate room-configuration
action (2/13).

Pause (2/7) was subsequently verified through Mutti: the command receipt was
accepted, the operator observed the robot stop, Xiaomi Home showed "Pausing",
and repeated reads returned status 5 with station mode 0 and unchanged cleaning
counters. Resume (2/8) was then verified with an accepted receipt and a 5→4 transition.
The active room/mode configuration and accumulated counters were retained,
consistent with continuing the paused task. Stop-and-return and return-for-mop-wash
remain distinct actions requiring their own physical verification.

Dock (3/1), invoked once via Mutti during the resumed run, was accepted and
produced status 6 (Returning), followed by status 14 with station mode 3 while
the operator saw "Cleaning the mop". The active room selection was cleared
from 2/40 during return. This differs from the automatic in-task wash return
(status 20, then 7, with the room selection retained). Do not present this
`dock` command as a temporary return-for-mop-wash action. Action 2/36 (`Back Mop
Wash`) is listed separately in the model specification and has not been tested
or added to this API.


### Drying and starting another cleaning (0.4.4)

`read()` includes `telemetry.station_mode`, `telemetry.station_operation`, and
`controls.can_start` / `controls.can_end_drying`. The model-specific observed
modes are 0 idle, 1 drying and 3 washing mops; mode 2 and other values remain
unknown. Main status still matters: status 7 is preparation/in-task washing,
while status 14 with mode 3 was observed after a manual task-ending return.

Start accepts idle/charging (1/2/9) and **status 14 + station mode 1** (drying).
It revalidates after applying settings. Missing, malformed or unknown station
data cannot unlock a status-14 start, and washing stays blocked. The operator
reported that Xiaomi Home permits a new cleaning while drying. This admission
rule has synthetic coverage; an actual start from drying through this updated
API is still to be verified. Start sends no implicit stop-drying command.

`vacuum.cleaning.command('end_drying')` invokes **2/32 Stop Dry**, after a fresh
read confirms drying. It does not use **2/2 Stop Sweeping**. The wire contract is
tested; physical end-drying behavior awaits a separate operator-triggered test.
Readiness while drying does not mean the robot is currently cleaning, and the
selected cleaning program must not be used as its activity label.
