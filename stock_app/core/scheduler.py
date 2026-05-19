"""
定时任务调度器
"""
import time, threading
from datetime import datetime


class Scheduler:
    def __init__(self):
        self._thread = None
        self._stop   = threading.Event()
        self._task   = None
        self._time   = None
        self._last_run = None

    def start(self, time_str, task):
        self.stop()
        self._time = time_str
        self._task = task
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._time = None
        self._task = None

    def is_running(self):
        return (self._thread is not None and
                self._thread.is_alive() and
                not self._stop.is_set())

    def _loop(self):
        while not self._stop.is_set():
            if self._time:
                now    = datetime.now()
                target = now.strftime("%H:%M")
                today  = now.strftime("%Y-%m-%d")
                if target == self._time and self._last_run != today:
                    try:
                        self._task()
                        self._last_run = today
                    except Exception:
                        pass
            time.sleep(20)
