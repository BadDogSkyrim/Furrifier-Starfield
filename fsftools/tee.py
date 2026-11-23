"""--log: copy everything the terminal gets to a file as well.

stdout and stderr are both wrapped, so warnings, errors and a crash's traceback are logged too. A
progress bar's redraws (writes starting with a carriage return) go to the terminal only: the step's
own summary line follows them anyway.
"""
import atexit
import sys
from datetime import datetime
from pathlib import Path


class Tee:
    def __init__(self, terminal, log):
        self.terminal, self.log = terminal, log

    def write(self, text):
        self.terminal.write(text)
        if not text.startswith('\r') and not self.log.closed:
            self.log.write(text)
        return len(text)

    def flush(self):
        self.terminal.flush()
        if not self.log.closed:
            self.log.flush()

    def isatty(self):
        return self.terminal.isatty()

    def __getattr__(self, name):        # encoding, fileno and the rest: the terminal's
        return getattr(self.terminal, name)


def start(path) -> Path:
    """Log this run to `path` (replaced if it exists), headed by the command line and the time."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    log = open(path, 'w', encoding='utf-8')
    log.write(' '.join([Path(sys.executable).name] + sys.argv) + '\n')
    log.write(f'{datetime.now():%Y-%m-%d %H:%M:%S}\n\n')
    sys.stdout = Tee(sys.stdout, log)
    sys.stderr = Tee(sys.stderr, log)

    def finish():
        # Python flushes sys.stdout after the atexit hooks: give it back the terminal first.
        for name in ('stdout', 'stderr'):
            stream = getattr(sys, name)
            if isinstance(stream, Tee):
                stream.flush()
                setattr(sys, name, stream.terminal)
        log.close()
    atexit.register(finish)
    return path
