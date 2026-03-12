import time


class SystemTimeProvider:
    def now(self) -> float:
        return time.time()

