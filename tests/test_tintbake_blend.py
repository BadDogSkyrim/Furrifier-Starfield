"""sf_tintbake's crowd faces blend as the Creation Kit's FaceGen does: checked against a CK bake."""
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
from fsfdata import game_data  # noqa: E402
sys.path.insert(0, str(ROOT))
import sf_tintbake  # noqa: E402
import uv_transfer  # noqa: E402

CK = ROOT / 'tests' / 'fixtures' / 'ck_bake'
SK3 = r'Textures\Actors\FSFFox\faces\chargen\male_fox_sk3_color.dds'
DERM05 = r'Textures\Actors\FSFFox\faces\chargen\postblenddetails\dermaesthetic\male_fox_derm05_color.dds'
COMPLEX04 = r'Textures\Actors\FSFFox\faces\chargen\postblenddetails\complexion\Complexion04_color.dds'


def read_ck_color(path):
    b = Path(path).read_bytes()
    assert b[84:88] == b'DX10' and struct.unpack_from('<I', b, 128)[0] == 29, 'R8G8B8A8_UNORM_SRGB'
    h, w = struct.unpack_from('<II', b, 12)
    return np.frombuffer(b, np.uint8, h * w * 4, 148).reshape(h, w, 4)[..., :3] / 255.0


def test_colour_layers_match_the_ck():
    data = game_data()
    base, *layers = [uv_transfer.load_image(str(data / p)) for p in (SK3, DERM05, COMPLEX04)]
    got = sf_tintbake.composite(base, [(image, None, 1.0) for image in layers])
    error = np.abs(np.rint(got * 255) / 255 - read_ck_color(CK / '00005999_Color.dds'))
    assert error.max() < 0.01, error.max()
