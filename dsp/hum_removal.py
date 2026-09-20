"""
Mains-hum detection and removal.

- goertzel_magnitude: single-frequency energy estimate (2nd-order IIR
  recurrence), used instead of a full FFT since only a couple of target
  frequencies are ever checked.
- resolve_hum_freq: auto-detects 50Hz vs 60Hz hum (coarse Goertzel scan,
  then a fine +/-1Hz sweep for the true peak), or returns a forced value.
- hum_notch: chains narrow notch biquads (filters.multiband_eq) at the
  fundamental and its harmonics to remove the buzz, not just one tone.
"""

import numpy as np
from typing import Optional

from .filters import multiband_eq

def goertzel_magnitude(audio: np.ndarray, freq: float, sample_rate: int, n: Optional[int] = None) -> float:
    """
    Goertzel algorithm: efficiently estimate the energy at a single
    target frequency `freq` in `audio`, without computing a full FFT.

    This is the classic 2nd-order IIR recurrence:
        s[i] = x[i] + 2*cos(omega)*s[i-1] - s[i-2]
        magnitude^2 = s[N-1]^2 + s[N-2]^2 - 2*cos(omega)*s[N-1]*s[N-2]

    where omega = 2*pi*k/N and k is the bin index nearest `freq`. Used
    here to compare 50Hz vs 60Hz (and nearby) energy to auto-detect
    which mains hum frequency is actually present, without paying for a
    full spectrum (see resolve_hum_freq()).

    Args:
        audio: Input signal (1-D)
        freq: Target frequency in Hz
        sample_rate: Sampling rate in Hz
        n: Number of samples to analyze (defaults to len(audio))

    Returns:
        Energy (squared magnitude) at `freq`
    """
    if n is None or n > len(audio):
        n = len(audio)
    if n <= 0:
        return 0.0
    x = audio[:n]
    k = int(0.5 + (n * freq) / sample_rate)
    omega = 2 * np.pi * k / n
    coeff = 2 * np.cos(omega)

    s1 = s2 = 0.0
    for i in range(n):
        s0 = x[i] + coeff * s1 - s2
        s2 = s1
        s1 = s0

    return s1 * s1 + s2 * s2 - coeff * s1 * s2


def resolve_hum_freq(audio: np.ndarray, sample_rate: int, mode='auto') -> float:
    """
    Determine the mains-hum fundamental frequency to notch out.

    If `mode` is explicitly '50' or '60', use that directly. Otherwise
    ('auto'), use the Goertzel algorithm to compare energy at 50Hz vs
    60Hz over (up to) the first 2 seconds of `audio`, pick whichever is
    stronger as a starting point, then fine-tune by scanning +/-1Hz
    around that center in 0.1Hz steps for the true peak -- mains hum is
    rarely at an exact round number due to small grid/recording clock
    drift, so this "coarse then fine" search finds the real peak.

    Args:
        audio: Input signal (1-D) -- typically the first channel of the
            selected region
        sample_rate: Sampling rate in Hz
        mode: 'auto' | '50' | '60' | 50 | 60

    Returns:
        Detected (or forced) hum frequency in Hz
    """
    if mode in ('50', 50):
        return 50.0
    if mode in ('60', 60):
        return 60.0

    n = min(len(audio), int(sample_rate * 2))
    if n < 256:
        n = min(len(audio), 4096)
    sub = audio[:n]

    m50 = goertzel_magnitude(sub, 50, sample_rate, n)
    m60 = goertzel_magnitude(sub, 60, sample_rate, n)
    center = 60.0 if m60 > m50 else 50.0

    best, best_mag = center, 0.0
    f = center - 1.0
    while f <= center + 1.0 + 1e-9:
        m = goertzel_magnitude(sub, f, sample_rate, n)
        if m > best_mag:
            best_mag, best = m, f
        f += 0.1

    return best


def hum_notch(audio: np.ndarray, sample_rate: int, freq: float,
               harmonics: int = 8, q: float = 12.0) -> np.ndarray:
    """
    Hum Reduction: notch out mains hum by chaining narrow notch biquads
    at `freq` and each of its harmonics (2x, 3x, ... up to `harmonics`),
    exactly matching AudioMass's HumNotch effect (a chain of native
    BiquadFilterNode 'notch' filters, one per harmonic, Q=12 by
    default). Harmonics at or above the Nyquist frequency are skipped.

    Hum from mains electricity is rarely a pure single tone -- it is
    typically a fundamental (50 or 60Hz) plus a "buzz" of harmonics
    at integer multiples, so notching just the fundamental alone
    usually still leaves an audible buzz behind.

    Args:
        audio: Input audio array (1-D, mono)
        sample_rate: Sampling rate in Hz
        freq: Fundamental hum frequency in Hz (see resolve_hum_freq())
        harmonics: Number of harmonics to notch (including the
            fundamental itself as harmonic #1)
        q: Notch quality factor -- higher Q = narrower notch (less
            collateral damage to nearby frequencies)

    Returns:
        Filtered audio array, same length as input
    """
    bands = []
    nyquist = sample_rate * 0.5
    for h in range(1, harmonics + 1):
        f = freq * h
        if f >= nyquist:
            break
        bands.append({'type': 'notch', 'freq': f, 'gain': 0.0, 'q': q, 'on': True})

    return multiband_eq(audio, sample_rate, bands)
