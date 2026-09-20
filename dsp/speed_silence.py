"""
Duration-changing operations: speed/pitch change and silence trimming.

- change_speed: manual linear-interpolation resampling — changes
  duration AND pitch together, like a turntable speed knob.
- remove_silence: frame-energy thresholding + splicing (segment
  detection, not a filtering/convolution operation) that shortens long
  silent gaps while leaving short natural pauses untouched.
"""

import numpy as np

def change_speed(audio: np.ndarray, speed_factor: float = 1.0) -> np.ndarray:
    """
    Manual speed/pitch change via linear-interpolation resampling
    (changes duration AND pitch together, like a turntable speed
    knob -- this is deliberately the simple/coupled version, not a
    time-stretch-only algorithm).

    Derivation: to play back at speed_factor times the rate, we
    read the original signal at fractional positions
        t[n] = n * speed_factor,  n = 0, 1, 2, ...
    and reconstruct each output sample by linear interpolation
    between its two neighboring input samples:
        frac = t[n] - floor(t[n])
        y[n] = (1-frac)*x[floor(t[n])] + frac*x[floor(t[n])+1]

    This is the discrete form of sampling-rate conversion: it is the
    manual reconstruction-then-resample step, done directly on the
    index/fractional-position arrays without calling
    scipy.signal.resample or librosa.

    Args:
        audio: Audio samples (mono or stereo)
        speed_factor: >1 = faster & higher pitch, <1 = slower & lower
                       (e.g. 2.0 = double speed/octave up,
                             0.5 = half speed/octave down)

    Returns:
        Resampled audio; length is approximately len(audio)/speed_factor
    """
    speed_factor = max(0.1, min(speed_factor, 4.0))
    n_in = len(audio)
    n_out = max(1, int(n_in / speed_factor))

    # Fractional source positions for each output sample.
    t = np.arange(n_out, dtype=np.float64) * speed_factor
    idx_floor = np.floor(t).astype(np.int64)
    idx_floor = np.clip(idx_floor, 0, n_in - 2) if n_in > 1 else idx_floor
    frac = t - idx_floor

    if audio.ndim == 1:
        y = (1.0 - frac) * audio[idx_floor] + frac * audio[idx_floor + 1]
    else:
        frac_col = frac[:, np.newaxis]
        y = (1.0 - frac_col) * audio[idx_floor, :] + frac_col * audio[idx_floor + 1, :]

    return y


def remove_silence(audio: np.ndarray, sample_rate: int,
                    threshold_db: float = -40.0,
                    min_silence_ms: float = 300.0,
                    padding_ms: float = 50.0) -> np.ndarray:
    """
    Manual silence-gap removal via frame-energy thresholding.

    Not a filtering/convolution operation -- this is segment
    detection + splicing, built the same manual way as trim/join:
      1. split audio into fixed-size frames
      2. compute each frame's RMS energy in dB:
         frame_db = 20*log10(sqrt(mean(frame^2)))
      3. mark frames below threshold_db as "silent"
      4. keep only runs of silence shorter than min_silence_ms in
         full (short gaps are natural pauses, not dead air), and for
         runs at/above min_silence_ms, keep padding_ms at each edge
         and drop the rest
      5. concatenate the surviving frames (manual array splicing,
         same primitive as join_audio)

    Args:
        audio: Audio samples (mono or stereo)
        sample_rate: Sample rate in Hz
        threshold_db: Frames quieter than this are "silent"
        min_silence_ms: Minimum gap length before we start trimming it
        padding_ms: How much silence to leave at each trimmed edge

    Returns:
        Audio with long silent gaps shortened; same channel shape,
        shorter or equal length
    """
    frame_len = max(1, int(0.02 * sample_rate))  # 20ms analysis frames
    n = len(audio)
    n_frames = max(1, n // frame_len)

    mono_ref = audio if audio.ndim == 1 else audio.mean(axis=1)

    frame_db = np.full(n_frames, -120.0)
    for f in range(n_frames):
        start = f * frame_len
        end = min(start + frame_len, n)
        frame = mono_ref[start:end].astype(np.float64)
        rms = np.sqrt(np.mean(frame ** 2)) if len(frame) else 0.0
        frame_db[f] = 20.0 * np.log10(rms + 1e-12)

    is_silent = frame_db < threshold_db

    min_silence_frames = max(1, int(min_silence_ms / 20.0))
    padding_frames = max(0, int(padding_ms / 20.0))

    # Walk the silent/voiced frame mask and decide which frames survive.
    keep_frame = np.ones(n_frames, dtype=bool)
    i = 0
    while i < n_frames:
        if not is_silent[i]:
            i += 1
            continue
        j = i
        while j < n_frames and is_silent[j]:
            j += 1
        run_len = j - i
        if run_len >= min_silence_frames:
            # Long silent run: keep padding at each edge, drop the middle.
            cut_start = i + padding_frames
            cut_end = j - padding_frames
            for f in range(cut_start, cut_end):
                if 0 <= f < n_frames:
                    keep_frame[f] = False
        i = j

    kept_segments = []
    f = 0
    while f < n_frames:
        if keep_frame[f]:
            start_f = f
            while f < n_frames and keep_frame[f]:
                f += 1
            sample_start = start_f * frame_len
            sample_end = min(f * frame_len, n)
            kept_segments.append(audio[sample_start:sample_end])
        else:
            f += 1

    # Trailing partial frame beyond n_frames*frame_len (if any)
    tail_start = n_frames * frame_len
    if tail_start < n and (n_frames == 0 or keep_frame[-1]):
        kept_segments.append(audio[tail_start:n])

    if not kept_segments:
        return audio[:1].copy() if n > 0 else audio.copy()

    return np.concatenate(kept_segments, axis=0)
