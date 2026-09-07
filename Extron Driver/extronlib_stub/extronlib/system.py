"""Stub of extronlib.system for off-device testing.

Timer here does NOT run on a real clock; call `.fire()` to simulate a tick in
tests. Wait executes immediately. ProgramLog prints.
"""


class Timer:
    def __init__(self, Interval, Function=None):
        self.Interval = Interval
        self.Function = Function
        self.State = "Running"
        self.count = 0

    def Stop(self):
        self.State = "Stopped"

    def Restart(self):
        self.State = "Running"

    def Pause(self):
        self.State = "Paused"

    # Test helper (not part of the real API): simulate a tick.
    def fire(self):
        self.count += 1
        if self.Function and self.State == "Running":
            self.Function(self, self.count)


class Wait:
    def __init__(self, Time, Function=None):
        self.Time = Time
        self.Function = Function
        if Function:
            Function()


def ProgramLog(Entry, Severity="info"):
    print("[ProgramLog:%s] %s" % (Severity, Entry))
