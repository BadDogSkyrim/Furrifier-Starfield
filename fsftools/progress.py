"""A one-line progress display for the long steps: count, percent, time left.

Redraws in place on a terminal, at most a few times a second; elsewhere (output piped to a file,
tests) it stays quiet, since the step's own summary line follows anyway."""
import sys
import time


class Progress:
    def __init__(self, label, total=None, stream=None, every=0.2):
        self.label, self.total, self.done = label, total, 0
        self.stream = stream or sys.stderr
        self.live = getattr(self.stream, 'isatty', lambda: False)()
        self.every, self.start, self.drawn, self.width = every, time.time(), 0.0, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def update(self, n=1, note=''):
        self.done += n
        now = time.time()
        if self.live and (now - self.drawn >= self.every or self.done == self.total):
            self.drawn = now
            self._draw(self.text(now, note))

    def text(self, now=None, note=''):
        elapsed = (now or time.time()) - self.start
        if self.total:
            pct = 100 * self.done / self.total
            line = f"  {self.label}: {self.done}/{self.total} {pct:3.0f}%"
            if 0 < self.done < self.total:
                line += f", {_clock(elapsed * (self.total - self.done) / self.done)} left"
        else:
            line = f"  {self.label}: {self.done}, {_clock(elapsed)}"
        return line + (f"  {note}" if note else '')

    def _draw(self, line):
        line = line[:119]
        self.stream.write('\r' + line + ' ' * max(0, self.width - len(line)))
        self.stream.flush()
        self.width = len(line)

    def close(self):
        """Clear the line, so the step's summary prints where the bar was."""
        if self.live and self.width:
            self.stream.write('\r' + ' ' * self.width + '\r')
            self.stream.flush()
            self.width = 0


def _clock(seconds):
    s = int(seconds + 0.5)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
