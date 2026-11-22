"""Race TOML paths are relative to the TOML, so the data folder works wherever it's deployed."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fsftools.config import load_races  # noqa: E402

RACE = '''[race]
editorid = "TestRace"
plugin = "Test.esm"
crowd_manifests = ["../crowd/test/Test_male.variants.json", "{absolute}"]
'''


def test_crowd_manifests_are_relative_to_the_race_toml(tmp_path):
    races = tmp_path / 'furrify' / 'races'
    races.mkdir(parents=True)
    absolute = (tmp_path / 'elsewhere' / 'Test_female.variants.json').as_posix()
    (races / 'TestRace.toml').write_bytes(RACE.format(absolute=absolute).encode('utf-8'))

    cfg = load_races(races)['TestRace']

    assert [Path(p) for p in cfg.crowd_manifests] == [
        tmp_path / 'furrify' / 'crowd' / 'test' / 'Test_male.variants.json',
        Path(absolute)]
