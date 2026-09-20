"""
Dynamics processing and waveshaping: compressor, brickwall limiter,
distortion, and a delay line.

- apply_compressor: feed-forward soft-knee compressor (gain computer +
  attack/release envelope follower).
- apply_hard_limiter: a compressor pushed to ratio -> infinity, driven
  by a running peak envelope instead of the compressor's RMS-like one —
  used both as a standalone effect and as the mix-bus safety limiter in
  mixing.mix_tracks_to_stereo().
- apply_distortion: sample-wise waveshaping (hard clip / cubic soft clip).
- apply_delay: single-tap (optionally feedback) delay line, built by
  direct sample-index recursion rather than convolution.
"""

import numpy as np

def apply_compressor(audio: np.ndarray, sample_rate: int,
                      threshold_db: float = -24.0, ratio: float = 4.0,
                      knee_db: float = 6.0, attack_ms: float = 5.0,
                      release_ms: float = 100.0,
                      makeup_gain_db: float = 0.0) -> np.ndarray:
    """
    Apply dynamic range compression (manual feed-forward compressor).

    A compressor reduces the volume of parts of the signal that exceed
    a threshold, smoothing out loud/quiet variation. It has two stages:

    STAGE 1 - Static gain computer (soft-knee compression curve):
    Converts an input level (in dB) to a target gain reduction (in dB).
    Let x = input level (dB), T = threshold (dB), R = ratio, W = knee
    width (dB). The standard soft-knee curve (see e.g. the MATLAB Audio
    Toolbox Compressor block, or Giannoulis/Massberg/Reiss 2012,
    "Digital Dynamic Range Compressor Design - A Tutorial and Analysis"):

        if 2*(x - T) < -W:    y = x                     (below knee)
        if 2*|x - T| <= W:    y = x + (1/R - 1)*(x-T+W/2)^2 / (2*W)  (knee)
        if 2*(x - T) > W:     y = T + (x - T)/R          (above knee)

    where y is the target (compressed) level, so the gain reduction to
    apply is (y - x) dB.

    STAGE 2 - Attack/release envelope follower:
    The gain reduction is smoothed over time so it doesn't change
    instantaneously (which would cause audible clicks/distortion). This
    is a standard one-pole exponential smoother:

        gain[n] = gain[n-1] + coeff * (target_gain[n] - gain[n-1])

    where `coeff` depends on whether the signal is getting louder
    (release) or quieter/more-compressed (attack):

        coeff_attack  = 1 - exp(-1 / (attack_sec  * sample_rate))
        coeff_release = 1 - exp(-1 / (release_sec * sample_rate))

    Note on the Web Audio API's DynamicsCompressorNode: its internal
    algorithm is explicitly left unspecified by the W3C spec and differs
    per browser engine, so there is no single canonical algorithm to
    port from it. The formula implemented here is instead the standard,
    well-documented textbook compressor design referenced above.

    Args:
        audio: Input audio array (1-D, mono), values in [-1, 1]
        sample_rate: Sampling rate in Hz
        threshold_db: Level (dB) above which compression starts (e.g. -24)
        ratio: Compression ratio, e.g. 4.0 means 4:1 (typically 1-20)
        knee_db: Width of the soft-knee transition in dB (0 = hard knee)
        attack_ms: Time (ms) for gain reduction to engage
        release_ms: Time (ms) for gain reduction to release
        makeup_gain_db: Additional linear gain applied after compression,
            to compensate for the overall level reduction

    Returns:
        Compressed audio array
    """
    N = len(audio)
    y = np.zeros(N)

    attack_coeff = 1.0 - np.exp(-1.0 / (max(attack_ms, 0.001) / 1000.0 * sample_rate))
    release_coeff = 1.0 - np.exp(-1.0 / (max(release_ms, 0.001) / 1000.0 * sample_rate))

    makeup_linear = 10 ** (makeup_gain_db / 20.0)

    current_gain_db = 0.0  # smoothed gain reduction state, in dB (0 = no reduction)
    eps = 1e-10  # avoid log(0) for silence

    for n in range(N):
        x_n = audio[n]

        # --- Level detection: convert instantaneous sample to dB ---
        level_db = 20.0 * np.log10(max(abs(x_n), eps))

        # --- Stage 1: static soft-knee gain computer ---
        if 2 * (level_db - threshold_db) < -knee_db:
            target_level_db = level_db
        elif 2 * abs(level_db - threshold_db) <= knee_db:
            target_level_db = level_db + (1.0 / ratio - 1.0) * \
                (level_db - threshold_db + knee_db / 2.0) ** 2 / (2.0 * knee_db)
        else:  # 2*(level_db - threshold_db) > knee_db
            target_level_db = threshold_db + (level_db - threshold_db) / ratio

        target_gain_db = target_level_db - level_db  # <= 0, amount of reduction

        # --- Stage 2: attack/release smoothing ---
        if target_gain_db < current_gain_db:
            # Getting quieter (more reduction needed) -> use attack (fast)
            current_gain_db += attack_coeff * (target_gain_db - current_gain_db)
        else:
            # Getting louder (less reduction needed) -> use release (slow)
            current_gain_db += release_coeff * (target_gain_db - current_gain_db)

        # --- Apply smoothed gain + makeup gain ---
        gain_linear = 10 ** (current_gain_db / 20.0)
        y[n] = x_n * gain_linear * makeup_linear

    return y


def apply_distortion(audio: np.ndarray, drive_db: float = 12.0,
                      mode: str = 'soft') -> np.ndarray:
    """
    Manual waveshaping distortion: y[n] = f(a * x[n]), applied
    sample-by-sample with no filtering, where a = 10^(drive_db/20)
    pre-gains the signal into the shaping curve.

    Two hand-derived shaping functions:
      - 'hard': hard clip, f(v) = clamp(v, -1, 1)
                (a step in the transfer function -> odd harmonics,
                 the classic "clipping" sound)
      - 'soft': cubic soft clip,
                f(v) = v - v^3/3   for |v| <= 1
                f(v) = sign(v)*2/3 for |v| > 1
                (continuous, no sharp corner -> smoother saturation.
                 This is the truncated Taylor series of tanh(v), so it
                 approximates tanh-style soft clipping without calling
                 any library tanh/clip implementation.)

    Args:
        audio: Audio samples (mono or stereo)
        drive_db: Pre-gain (dB) pushed into the shaping curve before
                  clipping; higher = more aggressive distortion
        mode: 'soft' or 'hard'

    Returns:
        Distorted audio, same shape as input (post-shape, auto-scaled
        back to a comparable loudness so drive doesn't just add gain)
    """
    a = 10.0 ** (drive_db / 20.0)
    driven = a * audio

    if mode == 'hard':
        y = np.clip(driven, -1.0, 1.0)
    else:
        v = driven
        cubic = v - (v ** 3) / 3.0
        y = np.where(np.abs(v) <= 1.0, cubic, np.sign(v) * (2.0 / 3.0))

    # The shaping curve saturates at a fixed ceiling (1.0 for hard,
    # 2/3 for soft) regardless of drive, so higher drive would
    # otherwise just make the output quieter on average once everything
    # is pinned to that ceiling. Rescale by the curve's own max output
    # so drive controls *character* (how squashed the wave looks),
    # not overall level.
    ceiling = 1.0 if mode == 'hard' else 2.0 / 3.0
    return y / ceiling


def apply_delay(audio: np.ndarray, sample_rate: int, delay_ms: float = 300.0,
                 feedback: float = 0.0, mix: float = 0.5) -> np.ndarray:
    """
    Manual single-tap delay line: y[n] = x[n] + mix*fb[n], built by
    direct sample-index addition (no convolution call) -- this is the
    time-domain implementation of a delay line rather than the
    impulse-response/convolution route Echo uses above.

    With feedback > 0 this becomes a recursive (IIR) system:
        fb[n] = x[n - D] + feedback * fb[n - D]
    i.e. each repeat feeds back into the next, so taps decay
    geometrically like echo but are generated by direct recursion
    on the sample array instead of building h[n] and convolving.

    Args:
        audio: Audio samples (mono or stereo)
        sample_rate: Sample rate in Hz
        delay_ms: Delay time in milliseconds
        feedback: 0-0.95, how much of each repeat feeds into the next
        mix: 0=dry only, 1=wet(delay) only

    Returns:
        Delayed/mixed audio, same length as input
    """
    d = max(1, int((delay_ms / 1000.0) * sample_rate))
    feedback = float(np.clip(feedback, 0.0, 0.95))
    n = len(audio)

    wet = np.zeros_like(audio, dtype=np.float64)
    dry = audio.astype(np.float64)

    # Direct recursive fill: for each output sample, add the delayed
    # tap (dry signal from D samples ago) plus feedback*previous wet
    # sample from D samples ago. This is a manual IIR recursion,
    # sample-index by sample-index -- no scipy.signal.lfilter.
    if audio.ndim == 1:
        for i in range(d, n):
            wet[i] = dry[i - d] + feedback * wet[i - d]
    else:
        for i in range(d, n):
            wet[i, :] = dry[i - d, :] + feedback * wet[i - d, :]

    y = (1.0 - mix) * dry + mix * wet

    peak = np.max(np.abs(y))
    if peak > 1.0:
        y = y / peak
    return y


def apply_hard_limiter(audio: np.ndarray, sample_rate: int,
                        ceiling_db: float = -0.3,
                        release_ms: float = 50.0) -> np.ndarray:
    """
    Manual brickwall limiter: a compressor with ratio -> infinity,
    zero attack, driven by a running peak envelope.

    Unlike apply_compressor() above (soft-knee, finite ratio, smoothed
    attack+release on an RMS-like envelope), a limiter's job is a hard
    ceiling: no sample may exceed the threshold, checked on every
    sample rather than smoothed in.

    Manual peak-envelope-follower derivation:
      1. instant gain needed at n: g_target[n] = min(1, ceiling/|x[n]|)
      2. one-pole release smoothing (attack is instant -- we can never
         smooth INTO a limit or we'd allow an overshoot):
         g[n] = g_target[n]                    if g_target[n] < g[n-1]
         g[n] = g[n-1] + (1-r)*(1 - g[n-1])     otherwise (releasing)
         where r = exp(-1 / (release_ms/1000 * sample_rate)) is the
         same one-pole time-constant formula used in apply_compressor.
      3. y[n] = g[n] * x[n]

    Args:
        audio: Audio samples (mono or stereo)
        sample_rate: Sample rate in Hz
        ceiling_db: Output ceiling in dBFS (samples never exceed this)
        release_ms: Time (ms) for gain to recover after a peak passes

    Returns:
        Limited audio, same shape as input, peak <= ceiling_db
    """
    ceiling = 10.0 ** (ceiling_db / 20.0)
    r = np.exp(-1.0 / (max(release_ms, 0.1) / 1000.0 * sample_rate))

    def _limit_channel(x: np.ndarray) -> np.ndarray:
        n = len(x)
        gain = np.ones(n, dtype=np.float64)
        g_prev = 1.0
        abs_x = np.abs(x) + 1e-12

        for i in range(n):
            g_target = min(1.0, ceiling / abs_x[i])
            if g_target < g_prev:
                # Instant attack: clamp down immediately, no smoothing,
                # so we never let an over-threshold sample through.
                g_now = g_target
            else:
                # Smooth release back toward unity gain.
                g_now = g_prev + (1.0 - r) * (1.0 - g_prev)
                g_now = min(g_now, g_target) if g_target < 1.0 else g_now
            gain[i] = g_now
            g_prev = g_now

        return x * gain

    if audio.ndim == 1:
        return _limit_channel(audio)
    else:
        left = _limit_channel(audio[:, 0])
        right = _limit_channel(audio[:, 1])
        return np.column_stack([left, right])
