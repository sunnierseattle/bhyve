# B‑hyve API + watering knowledge

Everything reverse‑engineered and decided while building this. Two parts:
the **API** (what the backend exposes) and the **agronomy** (how we water the
tomatoes and why).

---

## Part 1 — API reference (unofficial)

Base: `https://api.orbitbhyve.com/v1` · WebSocket: `wss://api.orbitbhyve.com/v1/events`
All requests send header `orbit-app-id: Orbit Support Dashboard`.

### Auth
`POST /session` body `{"session": {"email", "password"}}` → returns
`orbit_api_key` (a JWT — **this is the token**, not `orbit_session_token`) and
`user_id`. Token expires; just re‑login. Pass it on every later call as header
`orbit-api-key`.

### Verified endpoints
| Verb | Path | Notes |
|---|---|---|
| GET | `/devices?user_id=` | list all devices |
| GET | `/devices/{id}` | full device detail |
| GET | `/sprinkler_timer_programs?device_id=` | list programs (schedules) |
| POST | `/sprinkler_timer_programs` | create program |
| PUT | `/sprinkler_timer_programs/{id}` | edit program |
| DELETE | `/sprinkler_timer_programs/{id}` | delete program |
| GET | `/meshes` | returns `[]` (hub‑bridged, no RF mesh) |

### Program schema
```json
{"sprinkler_timer_program": {
  "device_id": "...",
  "name": "Program B",
  "program": "a|b|c",                       // 3 slots, each independent
  "enabled": true,
  "budget": 100,                            // seasonal adjust %
  "frequency": {"type": "days", "days": [0,1,2,3,4,5,6]},  // 0=Sun … 6=Sat
  "start_times": ["05:00", "06:00"],        // "HH:MM", 24h
  "run_times": [{"station": 1, "run_time": 2}]   // run_time in MINUTES (1.5 = 90s accepted)
}}
```

### WebSocket
On connect send `{"event":"app_connection","orbit_session_token":<token>,"subscribe_device_id":<id>}`.
Then:
- **Run:** `{"event":"change_mode","device_id","timestamp":<iso>,"mode":"manual","stations":[{"station":1,"run_time":<min>}]}`
- **Stop:** same with `"stations": []`
- **Rain delay:** `{"event":"rain_delay","device_id","delay":<hours>}`

Inbound event types seen: `change_mode` (echo), `watering_in_progress_notification`
(has `current_station`, `run_time`, `total_run_time_sec`, `program`),
`battery_status` (`mv`), `rain_delay`. `run_time` in WS is also minutes
(`1.0` = 60 s).

### Caveats / gotchas (important)
- **No history/usage REST endpoint exists** (`watering_events`, `zone_reports`,
  `water_usage`, `water_logs` all 404). To keep history, **log the live event
  stream** (`log_events`). The frames carry per‑run station, duration, flow.
- **The battery timer is the source of truth.** Program edits return
  `pending_timer_ack: true`. If the timer is asleep and re‑syncs an older copy,
  it can **revert a pending edit**. Edits stick reliably only when the device is
  connected/awake. **Always re‑read after editing** to confirm it held. (This
  bit us once — a PUT silently reverted.)
- **REST device status lags** — the low‑power timer sleeps, so `status`
  (battery, `watering_statuses`, `rain_delay`) can be minutes stale. For
  real‑time truth, use the WebSocket stream, not the REST status.
- `GET /sprinkler_timer_programs/{id}` (single) → 404; list via the collection
  with `?device_id=`. PUT/DELETE on `/{id}` work fine.
- The app caps **start times at 4 per program** in its UI, but the **API has no
  practical limit** (tested to 48). Enables many‑pulse cycle‑and‑soak.
- **`set_rain_delay` is implemented but UNVERIFIED** — the WS send returned no
  ack frames and the (laggy) REST status didn't reflect it. Payload matches the
  documented protocol; needs end‑to‑end confirmation by watching a real
  scheduled run get skipped.
- `run_time: 1.5` (90 s) was accepted **and** held on read‑back, so this
  firmware does store sub‑minute run times. (Not guaranteed on all firmware.)

---

## Part 2 — watering agronomy & decision log

### The setup
Rooftop, Seattle. ~5–6 tomato plants crowded in one shallow rectangular trough.
Drip, **one 2 GPH emitter per plant**. Exposed → more sun/wind/reflected heat,
and the shallow trough **dries fast and overruns** on long pulses.

### Core principle: cycle‑and‑soak
The soil absorbs only ~90 s–2 min before water sheets out the drainage holes.
So **don't run longer — run more, shorter pulses spaced ≥45 min** so each soaks
in. Same/more total water, no runoff, deeper roots. This is why the many‑pulse
schedules exist.

### Water math (per emitter)
- 2 GPH × run‑minutes ÷ 60 = gal/pulse. 90 s pulse = **0.05 gal**; 2 min = 0.067 gal.
- gal/day = gal/pulse × number of pulses.

### Tomato demand (container, summer)
- Young / flowering, mild weather: ~0.3–0.5 gal/plant/day
- **Fruiting + heat: ~0.5–0.8 gal/plant/day**
- Consistency matters: erratic water → **blossom‑end rot** and **fruit cracking**.
  Steady cycle‑and‑soak is the right shape; just scale volume.

### Decision log
- **2026‑06‑11:** plants flowering, little fruit. Built Program B cycle‑and‑soak.
- Found 2‑min pulses overran → dropped to **90 s** pulses.
- **2026‑06‑12:** lots of fruit set → demand jumped early. 90 s × 6 (~0.30 gal)
  now low for fruiting. Expanded to **9 × 90 s** (~0.45 gal/day), window
  stretched to 04:30–08:15 AM + 18:00–19:30 PM.

### Current Program B
`04:30, 05:15, 06:00, 06:45, 07:30, 08:15, 18:00, 18:45, 19:30` — 9 pulses ×
90 s, every day. ≈ **0.45 gal/emitter/day**.

### TODO / next steps
- **Mid‑July (fruiting + heat):** ~0.45 gal will be light. Best fix = **add a
  2nd 2 GPH emitter per plant** (→ ~0.90 gal at same schedule) rather than
  piling on more pulses. Watch for afternoon wilting as the trigger.
- Use **rain delay** to skip Seattle wet spells (once verified).
- Run `log_events` to build the watering history the API won't give us.
- Only the summer dry season (~Jul–Sep) really needs this schedule.
