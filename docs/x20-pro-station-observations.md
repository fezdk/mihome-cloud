# X20 Pro station modes: observed evidence and remaining questions

Research and observations: 2026-11-09–10. Model: `xiaomi.vacuum.d102gl`.
This records read-only observation of operator-started tasks; it is not a new
production decoder. Measurements use a bounded collector and the existing cloud
session. Raw traces remain private; only protocol-level findings are included.

## Evidence hierarchy

The public [d102gl MIoT specification](https://miot-spec.org/miot-spec-v2/instance?type=urn:miot-spec-v2:device:vacuum:0000A006:xiaomi-d102gl:1)
defines `base-station-working-status` as a read/notify **string**, service 2,
property 18. It does not specify the JSON structure or enumerate its `mode`.
Our cloud responses contain `mode`, `runtime`, and `total_time`.

An actual read on this X20 Pro, while the operator reported **Drying** in Xiaomi
Home after returning/cancelling cleaning, yielded:

```json
{
  "status_code": 14,
  "program_code": 3,
  "station": {"mode": 1, "runtime": 0, "total_time": 0}
}
```

This pairs one real drying observation with mode 1. It does not establish all
transitions, that the field resets promptly, or the meaning/units of its timers.
Program 3 is the selected vacuum-and-mop program; it is not evidence of an active
floor-cleaning task.

## Direct observations on d102gl

| Robot/app phase | Main status | Station mode | Evidence and limits |
| --- | --- | --- | --- |
| Charging, no cleaning underway | 2 | 0 | Repeated fresh successful reads before the operator's start. |
| Initial mop preparation; app "Cleaning the mop" | 7 | 3 | Repeated reads after an accepted two-room vacuum-and-mop start; 2/40 matched the selected rooms and mode. Timers remained zero. This does not identify individual filling/draining substeps. |
| Floor cleaning; app "Cleaning" | 4 | 0 | Observed transition from 7 / mode 3 to 4 / mode 0. Selected two-room task and vacuum-and-mop mode persisted. The briefly reported "Positioning" label was not separately resolved at ten-second cadence. |
| Mid-task return; app "Returning midway" | 20 | 0 | Observed after floor cleaning (4 / mode 0). Station remains inactive during this return; this does not yet establish the subsequent dock/wash state. |
| Dock arrival during the task | 2 | 0 | One successful sample between return and renewed mop washing; charging alone did not mean the task had finished. |
| Mid-task mop wash; app "Cleaning the mop" | 7 | 3 | Repeated observations matched the initial preparation state. Area/time counters remained at their pre-return values. |
| Cleaning resumes after the wash | 4 | 0 | Operator reported "Cleaning" again; measured status and station mode returned to the earlier floor-cleaning pair. |
| Operator pauses via Mutti; app "Pausing" | 5 | 0 | Pause action 2/7 received an accepted receipt; operator heard the robot pause and Mutti showed Paused. Repeated successful reads retained the same area/time counters. |
| Operator resumes via Mutti; app "Cleaning" | 4 | 0 | Resume action 2/8 was accepted; status changed from 5 to 4 with the same active room/mode configuration and retained counters. |
| Operator requests Return to dock via Mutti; app "Returning" | 6 | 0 | Dock action 3/1 was accepted. Active room selection disappeared from 2/40 during return; accumulated counters persisted. This differs from the mid-task return status 20. |
| Mop wash after manual Return to dock; app "Cleaning the mop" | 14 | 3 | Repeated reads showed station work after the room selection was cleared. Unlike the in-task wash (7 / mode 3), this is consistent with post-task washing. Followed by operator-confirmed Drying with status 14 / mode 1; no automatic cleaning resumption was observed. |
| Drying after cancellation/return | 14 | 1 | Repeated after manual Return to dock and post-wash in the measured run, matching the operator's app label. Drying exit/reset remains to be measured. |

**Mode 3 must not be labelled Dust collection on X20 Pro from the external table
below:** our initial mop-washing observation contradicts that assignment as a
universal d102gl meaning. Mode 2 remains unassigned on this model. Interpret
station mode together with main status and retain unknown values.

## External reference hypotheses (not an X20 Pro enum)

The [xiaomi-vac decoder](https://github.com/letitbe-dull/xiaomi-vac/blob/d1eb941ac8a1c4991221a56b9ca0e380362584b4/custom_components/xiaomi_vac/device.py)
contains this mapping:

| JSON mode | Reference interpretation | Evidence for d102gl |
| --- | --- | --- |
| 0 | Idle | Matches our repeated idle baseline as well as an independent d102gl report. |
| 1 | Drying | Matches our real reading and operator's app observation. |
| 2 | Washing mops | Unverified on d102gl. |
| 3 | Dust collection | Contradicted as a universal label: observed during initial mop washing on d102gl. |
| Other | Unknown | Preserve the value; do not coerce to idle or invent a meaning. |

**Important model boundary:** that decoder was introduced with **ov31gl** base
station support, not d102gl verification. The pinned [profile source](https://github.com/letitbe-dull/xiaomi-vac/blob/d1eb941ac8a1c4991221a56b9ca0e380362584b4/custom_components/xiaomi_vac/spec/profiles/xiaomi.py)
only sets `BaseStationCapability` on OV31GL; D102GL derives from C107/OV21GL.
The [introducing commit](https://github.com/letitbe-dull/xiaomi-vac/commit/04b9c78babe7ac9d5e5fd723b56eb2f8d8021c08)
and [contributor discussion](https://github.com/letitbe-dull/xiaomi-vac/pull/40)
identify that hardware scope. Thus 0–3 is a useful hypothesis table, not a vendor
X20 Pro enum. The independent d102gl observation is in
[hass-xiaomi-miot #2710](https://github.com/al-one/hass-xiaomi-miot/issues/2710).

Do not import Dreame codes. [Tasshack's enum](https://github.com/Tasshack/dreame-vacuum/blob/fec086caf064f2681e8bcc7be20a0d0ef54f444d/custom_components/dreame_vacuum/dreame/types.py)
uses Washing=1 and Drying=2, and additionally has return/water-related states.
That is a different protocol/model family and contradicts our drying observation
if applied directly to the Xiaomi JSON mode.

## Water handling and additional signals

No separate d102gl mode for filling the wash tray or pumping dirty water was
found in the inspected sources. These could be substeps of the observed preparation/wash state (hypothesis),
or visible through other fields. Absence of a mode transition cannot distinguish
an unreported substep from one shorter than the polling/cloud update interval.

The official d102gl spec has:

- Main status 2/2: 7 `GoWash`, 12 `MultiTaskStationWorking`, 14
  `StationWorking`, 20 `WashBreak`; compare these with the station JSON, rather
  than deriving exact pump activity from their names. Floor activity can report
  4, 16 or 17. Status 12 versus 14 is a candidate distinction between an ongoing
  task's dock visit and other station work; verify actual transitions.
- 2/28 enables mop washing. 2/29 selects the wash trigger: 0 by room,
  1 by area, 2 by time. 2/61 (`Frequency Mop Wash No Tank`) is an enum:
  0 = 5 m², 1 = 10 m², 2 = 8 m²; the raw value is not a square-metre count.
  A one-time read returned recognized values and the first observed return
  matched the configured area interval. This supports interpreting the wash
  cadence, not separate filling/draining telemetry.
- 2/68 edge-sweep frequency: 1 every time, 2 every seven sweeps. This is a
  cleaning-pattern setting, not a signal that the map is being rebuilt.
- 2/31 drying duration: the configured 2/3/4-hour choice, **not** remaining time.
- 2/34 automatic drying: a configuration switch, **not** current drying state.
- 2/53 `water-check-list`, 2/54 `water-check-status` (Uncheck/Checking/Check
  Success/Check Fail), 2/35 auto water change and 2/62 installed flag. These relate
  to water-check/installation capabilities; their names do not establish ordinary
  wash-tray pump telemetry. The spec also has water self-check actions, which we
  will not invoke. Never treat `Checking=1` as verified water filling.
- 2/3 fault, 2/66 fault IDs, 2/70 plugin reminder, 2/72 notice: possible context
  for empty clean-water/full dirty-water conditions. A fault is not a normal pump
  phase; do not intentionally induce errors for this observation.
- Events 2/2 cleaning complete, 2/3 dust collection complete, 2/4 mop wash complete,
  2/5 drying complete. The spec exposes these events, but delivery through our
  existing polling connection has not been demonstrated. Do not equate a station
  visit or charging state with task completion.

Other-model properties 2/88 drying progress, 2/90 remaining drying time, 2/97
sewage tank and 2/98 water tank are in the OV31GL reference profile, but **absent
from the inspected d102gl spec**. They are not part of the default measurement;
any future explicit one-shot compatibility probe must retain return codes and
must not silently add unsupported fields to regular polling.

The ov51gl `docs/miot.md`/tools were also inspected; they did not provide a JSON
station-mode interpretation. No device firmware or official app modification
is required or proposed.

## Next user-started cleaning: focused, read-only capture

The bounded observation plan below is used only for an announced test window.
Prefer notice before pressing Start to capture idle and initial preparation.

1. Record an idle baseline and the app's current label before starting. Capture
   relevant configuration once (mop present, drying duration/auto-dry and water
   installation/check fields) without changing it.
2. Poll a small property batch through the existing saved cloud session:
   status 2/2, station JSON 2/18, program 2/4, charging 3/2, area 2/6, time 2/7,
   fault 2/3, fault IDs 2/66, reminder 2/70 and notice 2/72. Ten properties per
   request; no map downloads are needed for station decoding. For start diagnosis,
   also read current cleaning configuration 2/40 and action result 2/67; those
   values remain in the private trace, not public logs.
3. Normally use ten-second intervals. During short, explicitly observed station
   phases, use a bounded five-second window if needed, then return to ten seconds.
   No overlapping calls, catch-up bursts or automatic login. Back off/stop on
   errors. Bound the run (initially at most 90 minutes); use a slower tail for
   drying if the user wants to observe its end.
4. Preserve **each response's per-property code**, missing values, the complete
   raw station string and parsed JSON. Never carry forward an older successful
   property as if it were freshly read. Record request start/end UTC, monotonic
   elapsed time, latency and an explicit sample sequence. These are observation
   timestamps, not robot event timestamps.
5. Keep manual observation markers separate from telemetry, with timestamp and
   evidence source: exact app label, visible behavior, pump sound, or uncertain
   inference. Approximate user-message timing should carry uncertainty. This is
   the reference needed to identify wash/fill/drain phases.
6. Store results only in a new private directory, e.g.
   `private-maps/station-<UTC>/`, mode 0700/files 0600. Do not retain auth material,
   account/device identifiers, signed URLs or map data. Do not print raw payloads
   in shared logs. No credentials or private traces in commits/public issues.

Observe these phases in order, when they naturally occur:

| Physical/app phase | Question to resolve |
| --- | --- |
| Idle before start | Does station mode settle to 0? Are timers reset? |
| Initial mop preparation | Observed 7 / mode 3; repeat and follow entry/exit. |
| Clean-water supply / wetting | Separate mode or another JSON field/timer change? |
| Mop washing / scrubbing | Does mode 3 persist? Are there intermediate states? |
| Dirty-water pumping | Separate signal, or still the same wash mode? |
| Leaving the dock / floor mopping | Does mode reset to 0, stay at its last value, or lag? |
| Mid-task return and wash | Does main status 12 differ from final/cancelled station work? |
| Resume floor cleaning | Does the same task continue? Do counters continue? |
| User cancellation / final return | Separate operator marker; do not infer it from charging. |
| Dust collection, if naturally enabled | Which value appears? Do not assume mode 3; it was observed during mop preparation. |
| Drying | Does mode 1 remain stable? Do timers ever become meaningful? |
| Drying ends / idle | Observe 1→0 if available; distinguish fresh reset from stale data. |

For the observed **floor cleaning** phase, the station reset to mode 0 while
main status became 4 and program remained 3. This is an observed entry transition,
not proof of reset behavior in every cycle. Continue checking mid-task returns
and final washing/drying. A short phase can be missed at ten-second cadence.

## Acceptance before exposing richer activity labels

Require repeated phase-labelled observations, including entry/exit and mid-task
versus final wash, before treating the candidate values as d102gl mappings.
Keep robot activity, selected program and station operation separate in the API.
Unknown, unsupported and stale are distinct outcomes. A display can eventually
say Drying with an observed-model interpretation, while retaining raw mode and
its evidence provenance. Exact fill/drain labels require their own demonstrated
signal. The cleaning-plan API now exposes the observed station interpretations, retaining
unknown modes. Only status 14 plus mode 1 permits a new start while the station
works. Filling/draining, mode 2 and drying completion remain unverified.
