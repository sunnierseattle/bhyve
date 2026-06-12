# bhyve

Control an **Orbit B‑hyve** smart sprinkler timer over Wi‑Fi from Python, using
the unofficial `api.orbitbhyve.com` REST + WebSocket backend (the same one the
B‑hyve app uses). Built for a rooftop tomato garden in Seattle.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install requests websocket-client
```

Create `.env` (gitignored, `chmod 600`) with your B‑hyve app login:

```
BHYVE_EMAIL=you@example.com
BHYVE_PASSWORD=...
```

## Library usage

```python
from bhyve import BhyveClient

c = BhyveClient.from_env()           # logs in using .env
for d in c.devices():
    print(d["name"], d["id"])

# manual run / stop (real-time, over WebSocket)
c.run("<device_id>", station=1, minutes=2)
c.stop("<device_id>")

# programs (schedules)
c.get_programs("<device_id>")
spec = c.build_program("<device_id>", slot="b", name="Program B",
    start_times=["05:00","06:00"], run_times=[{"station":1,"run_time":2}])
c.create_program(spec)               # POST  (new)
c.update_program("<program_id>", spec)   # PUT  (edit)
c.delete_program("<program_id>")     # DELETE

# rain delay (hours; 0 clears) — see caveat below
c.set_rain_delay("<device_id>", 24)

# live event stream + logging (recovers the history the REST API doesn't keep)
for evt in c.watch("<device_id>"):
    print(evt)
c.log_events("<device_id>", "events.ndjson")
```

## CLI

```bash
./.venv/bin/python bhyve.py devices
./.venv/bin/python bhyve.py programs <device_id>
./.venv/bin/python bhyve.py run <device_id> <station> <minutes>
./.venv/bin/python bhyve.py stop <device_id>
./.venv/bin/python bhyve.py rain-delay <device_id> <hours>
./.venv/bin/python bhyve.py delete-program <program_id>
./.venv/bin/python bhyve.py watch <device_id>
./.venv/bin/python bhyve.py log <device_id> <file>
```

## Hardware

| Device | Type | ID |
|---|---|---|
| Smart Sprinkler Timer | `sprinkler_timer` | `<device_id>` |
| Wi‑Fi Hub | `bridge` | `<hub_id>` |

Device IDs are account‑specific — find yours with `bhyve.py devices`. Optionally
store your timer's ID in `.env` as `BHYVE_DEVICE_ID` (gitignored) so you don't
paste it on every command.

- 1 station, **drip**, one **2 GPH emitter per plant**, ~5–6 tomato plants in a
  shallow rooftop trough.
- Programs: slot **a** = "Rooftop Garden", slot **b** = "Program B" (the tomato
  cycle‑and‑soak schedule this repo manages).

See [`KNOWLEDGE.md`](./KNOWLEDGE.md) for the full API reference and the watering
agronomy / decision log.
