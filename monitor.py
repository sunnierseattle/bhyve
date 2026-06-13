"""Resilient B-hyve watering monitor: prints relevant events with PDT
timestamps and auto-reconnects on drop. stdout is the event stream."""
import os, json, time
from datetime import datetime, timezone, timedelta
from bhyve import BhyveClient

RELEVANT = {
    "watering_in_progress_notification", "watering_complete",
    "change_mode", "device_idle", "low_battery",
}


def stamp():  # Seattle = PDT = UTC-7
    return (datetime.now(timezone.utc) - timedelta(hours=7)).strftime("%H:%M:%S PDT")


def main():
    while True:
        try:
            c = BhyveClient.from_env()
            dev = os.environ["BHYVE_DEVICE_ID"]
            print(f"[{stamp()}] connected, watching {dev}", flush=True)
            for evt in c.watch(dev):
                e = evt.get("event", "?")
                if e in RELEVANT:
                    print(f"[{stamp()}] {e} | station={evt.get('current_station')} "
                          f"run_time={evt.get('run_time')} "
                          f"sec={evt.get('total_run_time_sec')} "
                          f"status={evt.get('status','')} "
                          f"program={evt.get('program','')}", flush=True)
            print(f"[{stamp()}] stream ended, reconnecting…", flush=True)
        except Exception as ex:
            print(f"[{stamp()}] error {type(ex).__name__}: {ex} — reconnecting", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
