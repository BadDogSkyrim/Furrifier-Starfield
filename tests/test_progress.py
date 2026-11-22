import io

from fsftools.progress import Progress, _clock


class Tty(io.StringIO):
    def isatty(self):
        return True


def test_quiet_when_not_a_terminal():
    out = io.StringIO()
    with Progress('Work', 3, stream=out) as bar:
        for _ in range(3):
            bar.update()
    assert out.getvalue() == '', 'piped output gets only the summary lines'


def test_counts_percent_and_time_left():
    bar = Progress('FaceGen', 4, stream=io.StringIO())
    bar.start -= 10
    bar.update()
    assert bar.text(note='Sarah').startswith('  FaceGen: 1/4  25%, 0:30 left  Sarah')


def test_redraws_in_place_and_clears_at_the_end():
    out = Tty()
    with Progress('Loading plugins', 2, stream=out, every=0) as bar:
        bar.update(1, 'Starfield.esm')
        bar.update(1, 'FSF.esm')
    text = out.getvalue()
    assert text.count('\r') >= 3 and 'Loading plugins: 2/2 100%' in text
    assert text.endswith('\r') and text.rsplit('\r', 2)[1].strip() == '', 'line cleared for the summary'


def test_no_total_shows_count_and_elapsed():
    bar = Progress('Classifying NPCs', stream=io.StringIO())
    bar.update(); bar.update()
    assert bar.text().startswith('  Classifying NPCs: 2, 0:00')
    assert _clock(3725) == '1:02:05'
