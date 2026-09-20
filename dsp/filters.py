"""
Biquad (2nd-order IIR) filters and the EQ effects built from them.

- biquad_coefficients / biquad_apply: the shared 5-coefficient
  Direct-Form-1 recursion (Audio EQ Cookbook formulas), and running it
  over a signal. Every filter type below (peaking, shelf, highpass,
  lowpass, notch) is just a different set of these 5 coefficients.
- biquad_peaking_filter / parametric_eq: a single peaking band, and a
  fixed 3-band (low/mid/high) EQ built by chaining three of them.
- multiband_eq: the generic engine behind Paragraphic EQ and Graphic
  EQ — an arbitrary-length cascade of second-order sections (SOS),
  fused into one pass over the samples.
"""

import numpy as np
from typing import Tuple

def biquad_coefficients(filter_type: str, sample_rate: int, freq: float,
                         gain_db: float = 0.0, q: float = 1.0) -> Tuple[float, float, float, float, float]:
    """
    Compute normalized biquad coefficients (b0,b1,b2,a1,a2; a0 already
    divided out) for one 2nd-order IIR filter section, following the
    standard Audio EQ Cookbook formulas (R. Bristow-Johnson) — the same
    formulas the Web Audio API's native BiquadFilterNode implements
    internally, and the same ones AudioMass relies on for its Paragraphic
    EQ / Graphic EQ (it hands these params to createBiquadFilter()).

    Supported types (matches Paragraphic/Graphic EQ band types):
        'peaking'   - boost/cut a band around `freq` (uses gain_db, q)
        'highpass'  - attenuate below `freq` (2nd-order Butterworth-ish
                       response when q = 1/sqrt(2); gain_db unused)
        'lowpass'   - attenuate above `freq` (gain_db unused)
        'lowshelf'  - boost/cut everything below `freq` (uses gain_db, q)
        'highshelf' - boost/cut everything above `freq` (uses gain_db, q)

    Common terms:
        A     = 10^(gain_dB/40)              (only used by peaking/shelf)
        w0    = 2*pi*freq/sample_rate
        alpha = sin(w0) / (2*Q)               (bandwidth term)
        cos_w0, sin_w0 = cos(w0), sin(w0)

    Args:
        filter_type: One of 'peaking' | 'highpass' | 'lowpass' | 'lowshelf' | 'highshelf'
        sample_rate: Sampling rate in Hz
        freq: Center/cutoff frequency in Hz
        gain_db: Boost (+) or cut (-) in dB — ignored for highpass/lowpass
        q: Quality factor / bandwidth control

    Returns:
        (b0, b1, b2, a1, a2) with a0 already normalized to 1, i.e. ready
        to drop straight into:
            y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]
    """
    freq = min(max(freq, 1.0), sample_rate / 2.0 - 1.0)  # keep w0 in valid range
    q = max(q, 1e-4)

    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * freq / sample_rate
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    alpha = sin_w0 / (2 * q)

    if filter_type == 'peaking':
        b0 = 1 + alpha * A
        b1 = -2 * cos_w0
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * cos_w0
        a2 = 1 - alpha / A

    elif filter_type == 'highpass':
        b0 = (1 + cos_w0) / 2
        b1 = -(1 + cos_w0)
        b2 = (1 + cos_w0) / 2
        a0 = 1 + alpha
        a1 = -2 * cos_w0
        a2 = 1 - alpha

    elif filter_type == 'lowpass':
        b0 = (1 - cos_w0) / 2
        b1 = 1 - cos_w0
        b2 = (1 - cos_w0) / 2
        a0 = 1 + alpha
        a1 = -2 * cos_w0
        a2 = 1 - alpha

    elif filter_type == 'notch':
        # Rejects a narrow band around `freq` (opposite of 'peaking' with
        # a hard cut instead of a gain knob) -- used by Hum Reduction to
        # null out mains hum at 50/60Hz and its harmonics. gain_db unused.
        b0 = 1
        b1 = -2 * cos_w0
        b2 = 1
        a0 = 1 + alpha
        a1 = -2 * cos_w0
        a2 = 1 - alpha

    elif filter_type == 'lowshelf':
        sq = 2 * np.sqrt(A) * alpha
        b0 = A * ((A + 1) - (A - 1) * cos_w0 + sq)
        b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
        b2 = A * ((A + 1) - (A - 1) * cos_w0 - sq)
        a0 = (A + 1) + (A - 1) * cos_w0 + sq
        a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
        a2 = (A + 1) + (A - 1) * cos_w0 - sq

    elif filter_type == 'highshelf':
        sq = 2 * np.sqrt(A) * alpha
        b0 = A * ((A + 1) + (A - 1) * cos_w0 + sq)
        b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
        b2 = A * ((A + 1) + (A - 1) * cos_w0 - sq)
        a0 = (A + 1) - (A - 1) * cos_w0 + sq
        a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
        a2 = (A + 1) - (A - 1) * cos_w0 - sq

    else:
        raise ValueError(f"Unknown biquad filter_type: {filter_type!r}")

    return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def biquad_apply(audio: np.ndarray, b0: float, b1: float, b2: float,
                  a1: float, a2: float) -> np.ndarray:
    """
    Run one Direct Form 1 biquad recursion over `audio` with pre-computed,
    already-normalized coefficients (a0 = 1):

        y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]

    This is the literal recursive/IIR definition — every sample still
    depends on the two previous *output* samples, so (unlike the FIR
    convolution above) it cannot be vectorized away with FFT tricks or
    numpy broadcasting; the recursion is inherently sequential.

    The loop below still computes the exact same formula as a naive
    ``for n in range(N): y[n] = ...`` version indexing into numpy arrays;
    the only change is using plain Python floats/lists for x/y instead of
    numpy scalar indexing, which avoids numpy's per-element dispatch
    overhead (a numpy scalar read/write is much slower than a Python list
    read/write in a tight loop). This is a constant-factor speed-up
    (commonly 3-6x), not an algorithmic shortcut — still O(N), still the
    same recursive formula, one multiply-add per sample either way.

    Args:
        audio: Input audio array (1-D, mono)
        b0, b1, b2, a1, a2: Normalized biquad coefficients (a0 = 1)

    Returns:
        Filtered audio array, same length as input
    """
    x = audio.tolist()  # plain Python list -> fast indexing in the loop below
    N = len(x)
    y = [0.0] * N

    x_prev1 = x_prev2 = 0.0
    y_prev1 = y_prev2 = 0.0

    for n in range(N):
        x_n = x[n]
        y_n = (b0 * x_n + b1 * x_prev1 + b2 * x_prev2
               - a1 * y_prev1 - a2 * y_prev2)
        y[n] = y_n

        x_prev2 = x_prev1
        x_prev1 = x_n
        y_prev2 = y_prev1
        y_prev1 = y_n

    return np.array(y)


def biquad_peaking_filter(audio: np.ndarray, sample_rate: int, freq: float,
                           gain_db: float, q: float = 1.0) -> np.ndarray:
    """
    Apply a single peaking-EQ band (manual second-order IIR filter).

    A peaking filter boosts or cuts a band of frequencies centered at
    `freq`, leaving frequencies far from it largely unchanged. It is the
    core building block of a parametric EQ.

    This is a Direct Form 1 biquad (2nd-order IIR / recursive filter):

        y[n] = (b0/a0)x[n] + (b1/a0)x[n-1] + (b2/a0)x[n-2]
                            - (a1/a0)y[n-1] - (a2/a0)y[n-2]

    Unlike the FIR filter used for Echo above (output depends only on
    past/current INPUT samples), this is an IIR filter: the output also
    depends on its own past OUTPUT samples, which is what lets a
    2nd-order filter shape frequency response using only 5 coefficients
    instead of thousands of convolution taps.

    Coefficients follow the standard peakingEQ formula from the Audio EQ
    Cookbook (R. Bristow-Johnson) — see biquad_coefficients() for the
    full derivation shared across all filter types.

    Args:
        audio: Input audio array (1-D, mono)
        sample_rate: Sampling rate in Hz
        freq: Center frequency of the band in Hz
        gain_db: Boost (positive) or cut (negative) in dB at `freq`
        q: Quality factor - higher Q = narrower band (typically 0.5-5)

    Returns:
        Filtered audio array, same length as input
    """
    b0, b1, b2, a1, a2 = biquad_coefficients('peaking', sample_rate, freq, gain_db, q)
    return biquad_apply(audio, b0, b1, b2, a1, a2)


def parametric_eq(audio: np.ndarray, sample_rate: int,
                   low_gain_db: float = 0.0, mid_gain_db: float = 0.0,
                   high_gain_db: float = 0.0,
                   low_freq: float = 250.0, mid_freq: float = 1000.0,
                   high_freq: float = 4000.0,
                   q: float = 1.0) -> np.ndarray:
    """
    3-band parametric EQ built by chaining three peaking filters in
    series (low/mid/high), the same technique AudioMass's ParametricEQ
    uses when it connects multiple BiquadFilterNodes back-to-back:

        y = PeakEQ_high( PeakEQ_mid( PeakEQ_low(x) ) )

    Args:
        audio: Input audio array (1-D, mono)
        sample_rate: Sampling rate in Hz
        low_gain_db, mid_gain_db, high_gain_db: Boost/cut per band (dB)
        low_freq, mid_freq, high_freq: Center frequency per band (Hz)
        q: Quality factor, shared across all three bands

    Returns:
        Equalized audio array
    """
    y = audio
    if low_gain_db != 0.0:
        y = biquad_peaking_filter(y, sample_rate, low_freq, low_gain_db, q)
    if mid_gain_db != 0.0:
        y = biquad_peaking_filter(y, sample_rate, mid_freq, mid_gain_db, q)
    if high_gain_db != 0.0:
        y = biquad_peaking_filter(y, sample_rate, high_freq, high_gain_db, q)
    return y


def multiband_eq(audio: np.ndarray, sample_rate: int, bands: list) -> np.ndarray:
    """
    Generic N-band EQ: chains an arbitrary list of biquad sections in
    series, each with its own type/frequency/gain/Q — the same "connect
    biquad nodes back-to-back" architecture AudioMass uses for BOTH its
    Paragraphic EQ (a handful of user-placed bands of mixed types) and its
    Graphic EQ / Graphic EQ (20 bands) (a fixed ladder of shelf + peaking
    bands, one per fader):

        y = Band_k( ... Band_2( Band_1( x ) ) ... )

    This is a textbook "cascade of second-order sections" (SOS) — the
    standard way any real filter bank (analog or digital) is built once
    you need more shaping than one biquad can give you.

    Two optimizations, both preserving the exact recursive definition
    (still one multiply-add per coefficient per sample, nothing skipped
    mathematically that changes the result):

    1. Bands with gain == 0 and a non-shelf type are dropped before the
       loop even starts — a peaking band at 0 dB is the identity filter
       (b0=1, b1=b2=a1=a2=0), so running samples through it changes
       nothing. This matters a lot for the 20-band Graphic EQ, where most
       faders usually sit at 0 dB.

    2. The remaining sections are all evaluated inside ONE pass over the
       samples (one Python-level loop over n, with an inner loop over the
       small number of active sections) instead of K separate passes that
       each allocate a full-length array and re-walk all N samples. This
       is the classic Direct-Form-1 SOS cascade: each section's output
       becomes the next section's input at the SAME time step n, so the
       whole cascade is still one O(N*K) computation — just done as a
       single fused traversal of the audio instead of K sequential
       traversals, which removes K-1 redundant full-array round trips
       (each of which pays Python/numpy list<->array conversion and loop
       setup overhead).

    Args:
        audio: Input audio array (1-D, mono)
        sample_rate: Sampling rate in Hz
        bands: List of dicts, each with keys:
            'type'   - 'peaking' | 'highpass' | 'lowpass' | 'lowshelf' | 'highshelf'
            'freq'   - center/cutoff frequency in Hz
            'gain'   - boost/cut in dB (ignored for highpass/lowpass)
            'q'      - quality factor
            'on'     - optional bool, defaults True (lets the UI disable
                       a band without deleting it, matching the Paragraphic
                       EQ's per-band ON/OFF toggle)

    Returns:
        Equalized audio array, same length as input
    """
    # --- Resolve each active band down to its 5 biquad coefficients ---
    sections = []  # list of (b0,b1,b2,a1,a2)
    for band in bands:
        if not band.get('on', True):
            continue
        btype = band.get('type', 'peaking')
        gain = float(band.get('gain', 0.0))
        freq = float(band.get('freq', 1000.0))
        q = float(band.get('q', 1.0)) or 1.0

        # highpass/lowpass always shape the signal (they're not a no-op at
        # gain=0, since gain doesn't apply to them); peaking/shelf bands
        # at 0 dB are true no-ops and can be skipped entirely.
        if btype not in ('highpass', 'lowpass', 'notch') and gain == 0.0:
            continue

        sections.append(biquad_coefficients(btype, sample_rate, freq, gain, q))

    if not sections:
        return audio.copy()

    K = len(sections)
    x = audio.tolist()
    N = len(x)

    # Per-section delay-line state: x[n-1], x[n-2], y[n-1], y[n-2].
    xp1 = [0.0] * K
    xp2 = [0.0] * K
    yp1 = [0.0] * K
    yp2 = [0.0] * K

    out = [0.0] * N

    for n in range(N):
        v = x[n]  # signal value flowing through the cascade at this time step
        for k in range(K):
            b0, b1, b2, a1, a2 = sections[k]
            y_n = b0 * v + b1 * xp1[k] + b2 * xp2[k] - a1 * yp1[k] - a2 * yp2[k]

            xp2[k] = xp1[k]
            xp1[k] = v
            yp2[k] = yp1[k]
            yp1[k] = y_n

            v = y_n  # this section's output feeds the next section's input

        out[n] = v

    return np.array(out)
