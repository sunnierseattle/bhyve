#!/usr/bin/env python3
"""Minimal Orbit B-hyve client (unofficial API).

Credentials come from the environment (or a sibling .env) so they never live
in source:
    BHYVE_EMAIL=you@example.com
    BHYVE_PASSWORD=...

Library:
    from bhyve import BhyveClient
    c = BhyveClient.from_env()
    for d in c.devices():
        print(d["name"], d["id"])
    c.run("<device_id>", station=1, minutes=5)
    c.stop("<device_id>")
    for evt in c.watch("<device_id>"):  # generator of dicts
        print(evt)

CLI:
    python bhyve.py devices
    python bhyve.py run  <device_id> <station> <minutes>
    python bhyve.py stop <device_id>
    python bhyve.py watch <device_id>
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import requests
import websocket  # websocket-client

BASE = "https://api.orbitbhyve.com/v1"
WS_URL = "wss://api.orbitbhyve.com/v1/events"
APP_ID = "Orbit Support Dashboard"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a sibling .env into os.environ (no override)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip("'\""))


class BhyveClient:
    """Thin wrapper over Orbit's REST + WebSocket backend."""

    def __init__(self, token: str, user_id: str):
        self.token = token
        self.user_id = user_id

    # ---- construction -----------------------------------------------------
    @classmethod
    def login(cls, email: str, password: str) -> "BhyveClient":
        r = requests.post(
            f"{BASE}/session",
            headers={"orbit-app-id": APP_ID},
            json={"session": {"email": email, "password": password}},
            timeout=20,
        )
        if r.status_code != 200:
            raise RuntimeError(f"login failed ({r.status_code}): {r.text[:300]}")
        data = r.json()
        return cls(token=data["orbit_api_key"], user_id=data["user_id"])

    @classmethod
    def from_env(cls) -> "BhyveClient":
        _load_dotenv()
        email = os.environ.get("BHYVE_EMAIL")
        password = os.environ.get("BHYVE_PASSWORD")
        if not email or not password:
            raise RuntimeError("Set BHYVE_EMAIL and BHYVE_PASSWORD (env or .env).")
        return cls.login(email, password)

    # ---- REST -------------------------------------------------------------
    @property
    def _headers(self) -> dict:
        return {"orbit-app-id": APP_ID, "orbit-api-key": self.token}

    def devices(self) -> list[dict]:
        r = requests.get(
            f"{BASE}/devices",
            headers=self._headers,
            params={"user_id": self.user_id},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()

    # ---- WebSocket control ------------------------------------------------
    def _open_ws(self, device_id: str) -> websocket.WebSocket:
        ws = websocket.create_connection(WS_URL, timeout=20)
        ws.send(json.dumps({
            "event": "app_connection",
            "orbit_session_token": self.token,
            "subscribe_device_id": device_id,
        }))
        return ws

    def _send(self, device_id: str, payload: dict, drain: float = 6.0) -> list[dict]:
        """Send one command; collect any frames returned within `drain` seconds."""
        ws = self._open_ws(device_id)
        frames: list[dict] = []
        try:
            ws.send(json.dumps(payload))
            ws.settimeout(drain)
            while True:
                try:
                    frames.append(json.loads(ws.recv()))
                except Exception:
                    break
        finally:
            ws.close()
        return frames

    def run(self, device_id: str, station: int = 1, minutes: float = 1.0) -> list[dict]:
        """Start a manual run of `station` for `minutes`. Returns server frames."""
        return self._send(device_id, {
            "event": "change_mode",
            "device_id": device_id,
            "timestamp": _now_iso(),
            "mode": "manual",
            "stations": [{"station": int(station), "run_time": float(minutes)}],
        })

    def stop(self, device_id: str) -> list[dict]:
        """Stop all watering (manual mode, no stations active)."""
        return self._send(device_id, {
            "event": "change_mode",
            "device_id": device_id,
            "timestamp": _now_iso(),
            "mode": "manual",
            "stations": [],
        })

    def watch(self, device_id: str):
        """Yield live event dicts until the connection drops or you break."""
        ws = self._open_ws(device_id)
        try:
            while True:
                yield json.loads(ws.recv())
        finally:
            ws.close()

    def log_events(self, device_id: str, path: str) -> None:
        """Append every live event as one JSON line to `path` (the history the
        REST API doesn't keep). Runs until interrupted."""
        with open(path, "a") as fh:
            for evt in self.watch(device_id):
                fh.write(json.dumps(evt) + "\n")
                fh.flush()

    # ---- Rain delay -------------------------------------------------------
    def set_rain_delay(self, device_id: str, hours: int) -> list[dict]:
        """Delay all watering by `hours` (0 clears the delay)."""
        return self._send(device_id, {
            "event": "rain_delay",
            "device_id": device_id,
            "delay": int(hours),
        })

    # ---- Programs (schedules) --------------------------------------------
    def get_programs(self, device_id: str) -> list[dict]:
        r = requests.get(
            f"{BASE}/sprinkler_timer_programs",
            headers=self._headers,
            params={"device_id": device_id},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def build_program(device_id: str, *, slot: str = "b", name: str = "Program",
                      start_times: list[str], run_times: list[dict],
                      days: list[int] | None = None, enabled: bool = True,
                      budget: int = 100) -> dict:
        """Assemble a program spec.

        start_times: ["05:00", "07:00", ...]
        run_times:   [{"station": 1, "run_time": 2}, ...]   (run_time in minutes)
        days:        0=Sun … 6=Sat; defaults to every day.
        """
        return {"sprinkler_timer_program": {
            "device_id": device_id,
            "name": name,
            "program": slot,
            "enabled": enabled,
            "budget": budget,
            "frequency": {"type": "days", "days": days or [0, 1, 2, 3, 4, 5, 6]},
            "start_times": start_times,
            "run_times": run_times,
        }}

    def create_program(self, spec: dict) -> dict:
        r = requests.post(
            f"{BASE}/sprinkler_timer_programs",
            headers=self._headers, json=spec, timeout=20,
        )
        r.raise_for_status()
        return r.json()

    def update_program(self, program_id: str, spec: dict) -> dict:
        r = requests.put(
            f"{BASE}/sprinkler_timer_programs/{program_id}",
            headers=self._headers, json=spec, timeout=20,
        )
        r.raise_for_status()
        return r.json()

    def delete_program(self, program_id: str) -> dict:
        r = requests.delete(
            f"{BASE}/sprinkler_timer_programs/{program_id}",
            headers=self._headers, timeout=20,
        )
        r.raise_for_status()
        return r.json()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _print_devices(client: BhyveClient) -> None:
    for d in client.devices():
        s = d.get("status", {}) or {}
        print(f"\n● {d.get('name')}  [{d.get('type')}]")
        print(f"    id:        {d.get('id')}")
        print(f"    connected: {d.get('is_connected')}  run_mode: {s.get('run_mode')}")
        for z in d.get("zones") or []:
            print(f"    station {z.get('station')}: {z.get('name') or '(unnamed)'}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    cmd, rest = args[0], args[1:]
    client = BhyveClient.from_env()
    if cmd == "devices":
        _print_devices(client)
    elif cmd == "run":
        for f in client.run(rest[0], int(rest[1]), float(rest[2])):
            print("←", f.get("event"), f.get("status", ""))
        print(f"→ station {rest[1]} running {rest[2]} min")
    elif cmd == "stop":
        client.stop(rest[0])
        print("→ stop sent")
    elif cmd == "watch":
        print("Watching (Ctrl-C to stop)…")
        try:
            for evt in client.watch(rest[0]):
                print("←", evt.get("event"), evt.get("status", ""))
        except KeyboardInterrupt:
            pass
    elif cmd == "log":  # log <device_id> <file>
        print(f"Logging events to {rest[1]} (Ctrl-C to stop)…")
        try:
            client.log_events(rest[0], rest[1])
        except KeyboardInterrupt:
            pass
    elif cmd == "rain-delay":  # rain-delay <device_id> <hours>
        client.set_rain_delay(rest[0], int(rest[1]))
        print(f"→ rain delay set to {rest[1]}h (0 = cleared)")
    elif cmd == "programs":  # programs <device_id>
        for p in client.get_programs(rest[0]):
            print(f"{p['program']}  {p['name']!r:24} enabled={p['enabled']} "
                  f"times={p['start_times']} runs={p['run_times']}")
    elif cmd == "delete-program":  # delete-program <program_id>
        client.delete_program(rest[0])
        print(f"→ deleted program {rest[0]}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
