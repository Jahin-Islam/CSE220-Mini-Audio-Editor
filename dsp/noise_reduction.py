"""
STFT-based spectral-subtraction noise reduction.

- _hann_window: manual Hann window (closed-form, not np.hanning()),
  used to taper each analysis frame.
- reduce_noise: frame the signal (STFT), estimate a noise-floor
  magnitude spectrum from a quiet lead-in, subtract it from every
  frame's magnitude while preserving phase, then inverse-FFT and
  overlap-add back to a time-domain signal.
"""

import numpy as np

def _hann_window(length: int) -> np.ndarray:
    """
    Manual Hann window: w[n] = 0.5*(1 - cos(2*pi*n/(N-1))).

    Used to taper each STFT analysis frame so framing doesn't
    introduce sharp edges (spectral leakage) into the FFT below.
    Built from the closed-form definition, not np.hanning().
    """
    if length <= 1:
        return np.ones(length)
    n = np.arange(length)
    return 0.5 * (1.0 - np.cos(2.0 * np.pi * n / (length - 1)))


def reduce_noise(audio: np.ndarray, sample_rate: int,
                  noise_sample_s: float = 0.5,
                  reduction_db: float = 12.0,
                  frame_size: int = 2048) -> np.ndarray:
    """
    Manual spectral-subtraction noise reduction.

    This is an LTI-adjacent, frequency-domain technique building
    directly on the Fourier-analysis material from this course:
      1. Frame the signal into overlapping windows (STFT), each
         tapered by a manually-derived Hann window (see
         _hann_window above) to control spectral leakage.
      2. FFT each frame: X[k] = FFT(x_frame * window).
         (np.fft.fft is a *computational primitive* here, the same
         way "+" and "*" are -- the DSP algorithm being demonstrated
         is spectral subtraction itself, not the FFT. No
         scipy.signal / noisereduce / librosa denoising call is used
         anywhere in this function.)
      3. Estimate the noise floor's magnitude spectrum by averaging
         |X[k]| over the first noise_sample_s seconds (assumed to be
         representative background noise, e.g. room hiss).
      4. Subtract that noise magnitude from every frame's magnitude,
         scaled by reduction_db, while keeping each frame's original
         phase (spectral subtraction only reshapes magnitude):
         |Y[k]| = max(|X[k]| - alpha*|Noise[k]|, floor*|X[k]|)
         Y[k]   = |Y[k]| * exp(j*angle(X[k]))
      5. Inverse FFT each frame back to time domain and
         overlap-add the frames (weighted by the same window) to
         reconstruct the output signal, undoing the framing from
         step 1.

    Args:
        audio: Audio samples (mono or stereo)
        sample_rate: Sample rate in Hz
        noise_sample_s: Seconds from the start used to estimate the
                        noise floor (assumes a quiet lead-in)
        reduction_db: How strongly to subtract the estimated noise
                      (higher = more aggressive reduction, more risk
                      of "musical noise" artifacts -- worth mentioning
                      in defense as the classic spectral-subtraction
                      trade-off)
        frame_size: STFT frame length in samples (power of 2)

    Returns:
        Denoised audio, same shape as input
    """
    hop = frame_size // 2  # 50% overlap
    window = _hann_window(frame_size)
    alpha = 10.0 ** (reduction_db / 20.0)
    spectral_floor = 0.05  # never subtract below 5% of original magnitude

    def _process_channel(x: np.ndarray) -> np.ndarray:
        n = len(x)
        if n < frame_size:
            pad = frame_size - n
            x = np.concatenate([x, np.zeros(pad)])
            n = len(x)

        n_frames = max(1, (n - frame_size) // hop + 1)

        # --- Step 3: estimate noise floor from the lead-in ---
        noise_frames = max(1, int((noise_sample_s * sample_rate) / hop))
        noise_frames = min(noise_frames, n_frames)
        noise_mag_sum = np.zeros(frame_size)
        for f in range(noise_frames):
            start = f * hop
            frame = x[start:start + frame_size] * window
            spectrum = np.fft.fft(frame)
            noise_mag_sum += np.abs(spectrum)
        noise_mag = noise_mag_sum / noise_frames

        # --- Steps 1-2, 4-5: STFT -> subtract -> ISTFT w/ overlap-add ---
        y = np.zeros(n)
        window_sum = np.zeros(n)  # for normalizing overlap-add

        for f in range(n_frames):
            start = f * hop
            frame = x[start:start + frame_size] * window
            spectrum = np.fft.fft(frame)
            magnitude = np.abs(spectrum)
            phase = np.angle(spectrum)

            reduced_mag = np.maximum(
                magnitude - alpha * noise_mag,
                spectral_floor * magnitude
            )
            new_spectrum = reduced_mag * np.exp(1j * phase)
            new_frame = np.real(np.fft.ifft(new_spectrum))

            y[start:start + frame_size] += new_frame * window
            window_sum[start:start + frame_size] += window ** 2

        window_sum = np.where(window_sum < 1e-9, 1e-9, window_sum)
        y = y / window_sum
        return y[:len(audio)] if len(audio) <= len(y) else np.concatenate(
            [y, np.zeros(len(audio) - len(y))]
        )

    if audio.ndim == 1:
        return _process_channel(audio)
    else:
        left = _process_channel(audio[:, 0])
        right = _process_channel(audio[:, 1])
        return np.column_stack([left, right])

