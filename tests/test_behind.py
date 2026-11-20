"""Words set behind a subject: the matte is made firm so a dim subject hides them fully."""
import numpy as np

from workprint.matte import solid_alpha
from workprint.render import BEHIND_MATTE


def test_solid_alpha_default_is_unchanged():
    out = solid_alpha(np.array([0.2, 0.35, 0.5, 0.65, 0.9]))
    assert np.allclose(out, [0.0, 0.0, 0.5, 1.0, 1.0])


def test_behind_matte_hides_words_under_a_soft_subject():
    out = solid_alpha(np.array([0.1, 0.25, 0.35, 0.45, 0.6]), *BEHIND_MATTE)
    assert np.allclose(out, [0.0, 0.0, 0.5, 1.0, 1.0])


def test_lifted_opens_a_dim_frame_to_full_range():
    from workprint.matte import lifted
    dim = np.tile(np.linspace(6, 40, 64, dtype=np.float32), (32, 1))[..., None].repeat(3, 2).astype(np.uint8)
    out = lifted(dim)
    assert out.shape == dim.shape and out.dtype == np.uint8
    assert out.min() <= 3 and out.max() >= 250
    assert (np.diff(out[0, :, 0].astype(int)) >= 0).all()   # order kept: darker stays darker
