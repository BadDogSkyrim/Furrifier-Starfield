"""--log: everything written to the terminal also goes to a file, without the progress redraws."""
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fsftools.tee import Tee  # noqa: E402


class Terminal(io.StringIO):
    def isatty(self):
        return True


def test_tee_copies_lines_but_not_redraws():
    term, log = Terminal(), io.StringIO()
    t = Tee(term, log)
    t.write('Loading\n')
    t.write('\r  Fitting: 3/10  30%')
    t.write('\r' + ' ' * 20 + '\r')
    t.write('Done\n')
    assert term.getvalue().count('Fitting') == 1, 'the terminal sees the redraw'
    assert log.getvalue() == 'Loading\nDone\n'
    assert t.isatty(), 'progress bars still draw on the terminal'


def test_log_has_the_command_and_the_run(tmp_path):
    """The log starts with the command line, then has what the terminal got, an error included."""
    log = tmp_path / 'run.log'
    proc = subprocess.run([sys.executable, str(ROOT / 'sf_furrify.py'), '--log', str(log),
                           '--scheme', str(tmp_path / 'nothing.toml')],
                          capture_output=True, text=True, cwd=ROOT)
    text = log.read_text(encoding='utf-8')
    assert 'sf_furrify.py' in text.splitlines()[0], 'the command line first'
    assert 'no scheme at' in text
    assert proc.stdout.strip().splitlines()[-1] in text
    assert 'Exception ignored' not in proc.stderr, 'the log closes cleanly at exit'
