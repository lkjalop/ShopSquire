"""Preserve the scalar pair statistic while replacing repeated pixel scans."""
import math

import numpy as np
import pytest

from src.app.security.steg_detector import _chi_square_lsb


def reference_score(channel):
    """Original scalar pair-count calculation, retained as a numerical oracle."""
    flat=channel.flatten().astype(np.int32)
    values=np.unique(flat & ~1)
    if len(values)<2:
        return 0.0
    chi2=0.0
    dof=0
    for value in values:
        even=int(np.sum(flat==value))
        odd=int(np.sum(flat==value+1))
        total=even+odd
        if total<2:
            continue
        expected=total/2.0
        chi2+=((even-expected)**2)/expected
        chi2+=((odd-expected)**2)/expected
        dof+=1
    if not dof:
        return 0.0
    z=(chi2-dof)/max(1.0,math.sqrt(2.0*dof))
    return float(min(1.0,max(0.0,0.5*(1.0+math.erf(-z/math.sqrt(2.0))))))


@pytest.mark.parametrize('seed',range(8))
def test_pair_statistic_matches_the_original_reference_for_seeded_channels(seed):
    channel=np.random.default_rng(seed).integers(0,256,size=(57,63),dtype=np.uint8)
    assert _chi_square_lsb(channel)==reference_score(channel)


@pytest.mark.parametrize('values',[
    [],[0],[255],[0,1],[0,0],[254,255],[255,255],
    list(range(256)),[0,1]*300,[0]*400+[1]*3,[0,1,254,255]*100,
])
def test_sparse_constant_balanced_and_extreme_byte_pairs_keep_their_statistic(values):
    channel=np.array(values,dtype=np.uint8)
    assert _chi_square_lsb(channel)==reference_score(channel)
