#!/usr/bin/env python3
"""One-shot private X20 Pro export using an existing session; no login/polling."""
import argparse
import json
import logging
import os
from pathlib import Path
import sys

from mihome_cloud import MiHomeCloud
from mihome_cloud.maps import MODEL, MapError, X20MapReader, geometry, render_png


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-state", required=True, help="Existing session JSON file, or - for stdin")
    parser.add_argument("--country", default="de")
    parser.add_argument("--device-id", help="Otherwise discover exactly one matching model")
    parser.add_argument("--output", required=True, type=Path, help="New private output directory")
    parser.add_argument("--all-maps", action="store_true", help="Also fetch reported saved maps (not backups)")
    args = parser.parse_args()
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    cloud = MiHomeCloud("", "", country=args.country)
    try:
        source = sys.stdin.read() if args.auth_state == "-" else Path(args.auth_state).read_text()
        state = json.loads(source)
        if not all(state.get(k) for k in ("user_id", "ssecurity", "service_token")):
            raise MapError("Incomplete saved session")
        cloud.restore_auth_state(state)
        did = args.device_id
        if did is None:
            response = cloud._rpc(cloud._base_url + "/home/device_list",
                                  {"getVirtualModel": False, "getHuamiDevices": 0},
                                  allow_reauth=False)
            if response.get("code") != 0:
                raise MapError("Device discovery rejected")
            devices = [d for d in (response.get("result") or {}).get("list", [])
                       if d.get("model") == MODEL]
            if len(devices) != 1:
                raise MapError("Expected exactly one X20 Pro; select --device-id")
            did = devices[0]["did"]
        # Refuse existing output directories to avoid overwrite/symlink accidents.
        args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
        reader = X20MapReader(cloud, did)
        metadata = reader.metadata()
        def save(name, value):
            path = args.output / name
            with path.open("xb") as handle:
                handle.write(value if isinstance(value, bytes) else
                             json.dumps(value, ensure_ascii=False, indent=2).encode())
        save("metadata.json", metadata)
        values = metadata["values"]
        room_info = values.get("room_info")
        management = values.get("map_management") or {}
        saved = management.get("map_array", [])
        if not isinstance(saved, list) or len(saved) > 10:
            raise MapError("Unexpected saved-map inventory")
        jobs = [("active", values.get("map_object"), None)]
        if args.all_maps:
            jobs.extend((f"saved-{i + 1}", entry.get("obj_name"), entry.get("map_id"))
                        for i, entry in enumerate(saved))
        fetched, manifest, failures = {}, [], 0
        for name, obj, expected in jobs:
            try:
                if not obj:
                    raise MapError("Missing reported object")
                if obj not in fetched:
                    fetched[obj] = reader.fetch(obj)
                raw, decoded = fetched[obj]
                # A saved slot can be stale or overwritten: verify its embedded map ID.
                if expected is not None and decoded.get("map_id") != expected:
                    raise MapError("Saved object map ID does not match inventory")
                save(name + ".raw", raw)
                save(name + ".json", decoded)
                # room_info belongs to current device state, not arbitrary stored floors.
                geom = geometry(decoded, room_info if name == "active" else None)
                save(name + "-geometry.json", geom)
                save(name + ".png", render_png(decoded))
                manifest.append({"file": name, "status": "exported", "map_id": decoded.get("map_id"),
                                 "room_count": len(geom["rooms"])})
                print(f"{name}: exported RAW, JSON, geometry JSON and PNG ({len(geom['rooms'])} rooms)")
            except Exception:
                # No exception repr: HTTP/library errors may contain signed URLs/payloads.
                failures += 1
                manifest.append({"file": name, "status": "failed"})
                print(f"{name}: export failed; private metadata retained", file=sys.stderr)
        save("manifest.json", manifest)
        return 1 if failures else 0
    except Exception:
        print("Export failed. Check session, network, device selection and a new output directory. No login was attempted.", file=sys.stderr)
        return 1
    finally:
        cloud.close()


if __name__ == "__main__":
    raise SystemExit(main())
