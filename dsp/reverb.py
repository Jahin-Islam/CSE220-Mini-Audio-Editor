"""
Convolution reverb: a synthetic exponentially-decaying noise impulse
response, convolved with the signal via convolution.discrete_convolution().

Modeled as the same kind of LTI system as Echo (see convolution.py's
create_echo_impulse) — the only difference is the impulse response
itself: Echo's is a sparse train of a few decaying spikes, Reverb's is
a dense decaying noise cloud.
"""

import numpy as np
from typing import Optional

from .convolution import discrete_convolution

def create_reverb_impulse(sample_rate: int, duration_s: float = 1.5,
                           decay: float = 2.0, reverse: bool = False,
                           seed: Optional[int] = None) -> np.ndarray:
    """
    Generate a synthetic reverb impulse response (exponentially-decaying
    noise) - the same technique used by convolution-reverb effects such
    as AudioMass's Reverb, which builds this kind of impulse and feeds
    it to the Web Audio API's native ConvolverNode.

    A real room's impulse response is dense, random-looking reflections
    that decay over time. Instead of recording a real room, this
    synthesizes an approximation: white noise shaped by an exponential
    decay envelope.

        h[n] = noise[n] * (1 - n/L)^decay      (or reversed if `reverse`)

    where:
    - noise[n] is uniform random noise in [-1, 1]
    - L is the impulse length in samples (duration_s * sample_rate)
    - decay controls how quickly the envelope falls off (higher = faster)

    Args:
        sample_rate: Sampling rate in Hz
        duration_s: Length of the reverb tail in seconds ("room size")
        decay: Decay exponent - higher values decay faster/shorter-sounding
        reverse: If True, reverses the envelope (reverse-reverb "swell")
        seed: Optional random seed, for reproducible/testable output

    Returns:
        Impulse response array, length = int(sample_rate * duration_s)
    """
    rng = np.random.RandomState(seed) if seed is not None else np.random

    length = int(sample_rate * duration_s)
    h = np.zeros(length)

    for i in range(length):
        n = (length - i) if reverse else i
        envelope = (1.0 - n / length) ** decay
        h[i] = (rng.random() * 2 - 1) * envelope

    return h


def apply_reverb(audio: np.ndarray, sample_rate: int, duration_s: float = 1.5,
                  decay: float = 2.0, mix: float = 0.3,
                  reverse: bool = False, seed: Optional[int] = None) -> np.ndarray:
    """
    Apply convolution reverb to an audio signal.

    Reverb is modeled as an LTI system, exactly like Echo above - the
    difference is only the impulse response used: Echo's h[n] is a
    sparse train of a few decaying spikes (discrete repeats you can
    hear as distinct echoes); Reverb's h[n] is a DENSE decaying noise
    cloud (thousands of overlapping "micro-echoes" that blur together
    into a smooth wash, the way a room's reflections do).

        output = dry_signal*(1-mix) + (signal convolved with h)*mix

    Args:
        audio: Input audio array (1-D, mono)
        sample_rate: Sampling rate in Hz
        duration_s: Reverb tail length in seconds ("room size")
        decay: Decay exponent (higher = shorter/tighter decay)
        mix: Wet/dry mix, 0.0 = fully dry (no effect), 1.0 = fully wet
        reverse: If True, produces a reverse-reverb swell
        seed: Optional random seed for reproducible impulse response

    Returns:
        Audio with reverb applied, same length as input (convolution
        tail truncated to match, same approach Echo uses above)
    """
    h = create_reverb_impulse(sample_rate, duration_s, decay, reverse, seed)

    # Reuses discrete_convolution() above - same LTI-system convolution
    # as Echo, just with a different (dense, noise-based) impulse response
    wet = discrete_convolution(audio, h)
    wet = wet[:len(audio)]  # truncate convolution tail to original length

    # Normalize wet signal so its loudness is comparable to the dry
    # signal, independent of the impulse response's length/energy
    wet_max = np.max(np.abs(wet))
    if wet_max > 1e-10:
        wet = wet / wet_max * np.max(np.abs(audio))

    y = (1.0 - mix) * audio + mix * wet
    return y
