"""Tests for bhyve.BhyveClient. Run: ./.venv/bin/python test_bhyve.py
(also discoverable by pytest). No network — the WebSocket is faked."""
import json
import websocket
import bhyve


class FakeWS:
    """Scripted stand-in for a websocket connection. 'TIMEOUT' entries raise
    the idle-read timeout; '' signals the server closing the socket."""
    def __init__(self, script):
        self.script = list(script)
        self.sent = []
        self.closed = False
        self.timeout = None

    def settimeout(self, t):
        self.timeout = t

    def recv(self):
        if not self.script:
            return ""
        item = self.script.pop(0)
        if item == "TIMEOUT":
            raise websocket.WebSocketTimeoutException("timed out")
        return item

    def send(self, msg):
        self.sent.append(msg)

    def close(self):
        self.closed = True


def test_watch_keepalive_and_pong_skip():
    """Regression test: an idle gap must trigger an app-level {"event":"ping"}
    (not kill the stream), pong replies are swallowed, real events yielded,
    and a server close ends iteration."""
    fake = FakeWS([
        "TIMEOUT",                                              # idle -> ping
        json.dumps({"event": "pong"}),                          # ack -> skipped
        json.dumps({"event": "watering_in_progress_notification",
                    "current_station": 1}),                     # real -> yielded
        "",                                                     # server close
    ])
    c = bhyve.BhyveClient(token="t", user_id="u")
    c._open_ws = lambda dev: fake                               # bypass network

    events = list(c.watch("dev", ping_interval=1))

    assert len(events) == 1, f"expected 1 event, got {len(events)}"
    assert events[0]["event"] == "watering_in_progress_notification"
    assert any(json.loads(s).get("event") == "ping" for s in fake.sent), \
        "no app-level ping sent during idle gap"
    assert fake.closed, "socket not closed on exit"


def test_build_program_shape():
    spec = bhyve.BhyveClient.build_program(
        "dev", slot="b", name="P",
        start_times=["05:00"], run_times=[{"station": 1, "run_time": 1.5}])
    p = spec["sprinkler_timer_program"]
    assert p["program"] == "b"
    assert p["frequency"] == {"type": "days", "days": [0, 1, 2, 3, 4, 5, 6]}
    assert p["run_times"][0]["run_time"] == 1.5


if __name__ == "__main__":
    test_watch_keepalive_and_pong_skip()
    test_build_program_shape()
    print("ok — all tests passed")
