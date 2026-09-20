"""
Basic sample-wise and array-level audio operations.

Manual DSP implementations (for oral defense):
- apply_gain: y[n] = a * x[n]
- apply_fade: multiplicative envelope (linear / raised-cosine ramp)
- reverse_audio: y[n] = x[N-1-n]
- normalize_audio: solves apply_gain's inverse problem (peak or RMS)
- invert_audio: polarity flip, y[n] = -x[n]

Plain array operations (not DSP algorithms, kept alongside the above
since callers reach for them in the same "operate on a signal" context):
- trim_audio: slicing
- join_audio: concatenation
"""

import numpy as np

def apply_gain(audio: np.ndarray, gain_db: float) -> np.ndarray:
    """
    Apply gain/scaling to audio signal (manual implementation).

    Mathematical operation: y[n] = a · x[n]

    where:
    - x[n] is the input sample at index n
    - a is the linear amplitude scaling factor
    - y[n] is the output sample

    Gain in dB is converted to linear scale: a = 10^(gain_dB/20)

    Args:
        audio: Input audio array
        gain_db: Gain in decibels (0 dB = no change, +6 dB ≈ double, -6 dB ≈ half)

    Returns:
        Scaled audio array
    """
    # Convert dB to linear amplitude scale
    a = 10 ** (gain_db / 20.0)

    # Sample-wise multiplication: y[n] = a * x[n]
    y = np.zeros_like(audio)
    for n in range(len(audio)):
        y[n] = a * audio[n]

    return y


def apply_fade(audio: np.ndarray, duration_samples: int, fade_type: str = 'in',
               curve: str = 'linear') -> np.ndarray:
    """
    Apply fade in or fade out (manual envelope construction).

    Fade is a time-varying gain: y[n] = g[n] · x[n]

    where g[n] is the envelope (gain as a function of time):

    Linear fade in:  g[n] = n / N  for n = 0, 1, ..., N-1
    Linear fade out: g[n] = (N - n) / N  for n = 0, 1, ..., N-1

    Raised cosine fade (smoother):
    Fade in:  g[n] = 0.5 * (1 - cos(π·n/N))
    Fade out: g[n] = 0.5 * (1 + cos(π·n/N))

    Args:
        audio: Input audio array
        duration_samples: Number of samples over which to fade
        fade_type: 'in' or 'out'
        curve: 'linear' or 'cosine' (raised cosine)

    Returns:
        Faded audio array
    """
    y = audio.copy()
    N = min(duration_samples, len(audio))

    # Build the envelope manually
    envelope = np.zeros(N)

    if curve == 'linear':
        for n in range(N):
            if fade_type == 'in':
                envelope[n] = n / N  # Linear ramp up: 0 → 1
            else:  # fade_type == 'out'
                envelope[n] = (N - n) / N  # Linear ramp down: 1 → 0

    elif curve == 'cosine':
        for n in range(N):
            if fade_type == 'in':
                # Raised cosine fade in: 0.5*(1 - cos(π·n/N))
                envelope[n] = 0.5 * (1.0 - np.cos(np.pi * n / N))
            else:  # fade_type == 'out'
                # Raised cosine fade out: 0.5*(1 + cos(π·n/N))
                envelope[n] = 0.5 * (1.0 + np.cos(np.pi * n / N))

    # Apply envelope: y[n] = g[n] * x[n]
    if fade_type == 'in':
        for n in range(N):
            y[n] *= envelope[n]
    else:  # fade_type == 'out'
        start = len(audio) - N
        for n in range(N):
            y[start + n] *= envelope[n]

    return y


def reverse_audio(audio: np.ndarray) -> np.ndarray:
    """
    Reverse audio signal (manual index reversal).

    Mathematical operation: y[n] = x[N-1-n]

    where:
    - x[n] is the input sample at index n
    - N is the total number of samples
    - y[n] is the reversed output

    Args:
        audio: Input audio array

    Returns:
        Reversed audio array
    """
    N = len(audio)
    y = np.zeros_like(audio)

    # Manual index reversal: y[n] = x[N-1-n]
    for n in range(N):
        y[n] = audio[N - 1 - n]

    return y


def normalize_audio(audio: np.ndarray, target_db: float = -1.0,
                     mode: str = 'peak') -> np.ndarray:
    """
    Manual normalization: scale so the loudest point (or RMS level)
    hits target_db, using the same gain law as apply_gain().

    y[n] = a * x[n], where a is chosen so that:
      - mode='peak': max(|y|) == 10^(target_db/20)
      - mode='rms':  sqrt(mean(y^2)) == 10^(target_db/20)

    This is Gain's inverse problem: instead of the caller choosing a,
    we solve for the a that hits a target level.

    Args:
        audio: Audio samples (mono or stereo)
        target_db: Desired peak or RMS level in dBFS (typically <= 0)
        mode: 'peak' or 'rms'

    Returns:
        Normalized audio, same shape as input
    """
    target_linear = 10.0 ** (target_db / 20.0)

    if mode == 'rms':
        current_level = np.sqrt(np.mean(audio.astype(np.float64) ** 2))
    else:
        current_level = np.max(np.abs(audio))

    if current_level < 1e-9:
        # Silent (or near-silent) input: nothing to scale against
        return audio.copy()

    a = target_linear / current_level
    y = a * audio

    # Peak-safety clamp: RMS-mode gain can still push transient peaks
    # past full scale, so re-check and rescale if needed.
    peak = np.max(np.abs(y))
    if peak > 1.0:
        y = y / peak

    return y


def invert_audio(audio: np.ndarray) -> np.ndarray:
    """
    Manual polarity inversion: y[n] = -x[n].

    Flips every sample's sign. For a single channel this is inaudible
    on its own (ear can't hear absolute phase), but it matters when
    mixed against another copy of the same signal (cancellation) or
    used to correct out-of-phase stereo/multi-mic recordings.

    Args:
        audio: Audio samples (mono or stereo)

    Returns:
        Polarity-inverted audio, same shape as input
    """
    return -audio


def trim_audio(audio: np.ndarray, start_sample: int, end_sample: int) -> np.ndarray:
    """
    Trim audio to a selected region.

    This is a straightforward array slicing operation, not a DSP algorithm.

    Args:
        audio: Input audio array
        start_sample: Start index (inclusive)
        end_sample: End index (exclusive)

    Returns:
        Trimmed audio array
    """
    return audio[start_sample:end_sample].copy()


def join_audio(audio1: np.ndarray, audio2: np.ndarray) -> np.ndarray:
    """
    Join/concatenate two audio clips.

    This is a straightforward array concatenation, not a DSP algorithm.

    Args:
        audio1: First audio array
        audio2: Second audio array

    Returns:
        Concatenated audio array
    """
    return np.concatenate([audio1, audio2])
