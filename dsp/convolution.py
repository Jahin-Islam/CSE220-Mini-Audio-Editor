"""
Discrete convolution — the core LTI-system building block used by
Echo (sparse impulse) and Reverb (dense noise impulse) elsewhere in
this package.

Manual implementations only (no np.convolve / scipy.signal.fftconvolve):
- discrete_convolution_direct: literal y[n] = sum_k x[k]*h[n-k]
- discrete_convolution: same definition, computed via the Convolution
  Theorem (FFT) for speed
- discrete_convolution_reference_slow: pure-Python reference kept only
  for correctness-checking the two above
- create_echo_impulse: builds an Echo effect's impulse response
"""

import numpy as np

def discrete_convolution_direct(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """
    Direct-form implementation of discrete convolution (no np.convolve).

    Definition: y[n] = Σ_{k=0}^{M-1} x[k] · h[n-k]

    where:
    - x[n] is the input signal (length N)
    - h[n] is the impulse response (length M)
    - y[n] is the output signal (length N+M-1)

    This is the direct form of linear convolution used in LTI system analysis.
    It is O(N*M): correct, and useful for the oral defense / small inputs,
    but too slow for anything beyond a few thousand samples in each of x, h
    (a 3-second echo impulse against a multi-second clip is already tens of
    millions of multiply-adds). See discrete_convolution() below for the
    frequency-domain version used by the app for real audio.

    Args:
        x: Input signal array
        h: Impulse response array

    Returns:
        Convolved output array of length len(x) + len(h) - 1
    """
    N = len(x)
    M = len(h)
    y_len = N + M - 1
    y = np.zeros(y_len)

    # Direct implementation of y[n] = sum_k x[n-k]*h[k], one output sample at a time.
    # The inner sum over k is the same definition as the original nested-loop version
    # (see discrete_convolution_reference_slow below for the literal scalar form used
    # for verification) — here it's written as a single vectorized dot product instead
    # of a scalar for-k loop.
    for n in range(y_len):
        # Valid k range so that both x[n-k] and h[k] are in bounds:
        #   0 <= k < M   and   0 <= n-k < N  =>  n-N+1 <= k <= n
        k_lo = max(0, n - N + 1)
        k_hi = min(M - 1, n)
        if k_lo > k_hi:
            continue
        # y[n] = sum_{k=k_lo}^{k_hi} x[n-k] * h[k], computed as one dot product
        # instead of a scalar for-k loop.
        x_slice = x[n - k_hi: n - k_lo + 1][::-1]  # x[n-k] for k = k_lo..k_hi
        h_slice = h[k_lo: k_hi + 1]
        y[n] = np.dot(x_slice, h_slice)

    return y


def discrete_convolution(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """
    Fast discrete convolution via the Convolution Theorem (still hand-derived
    DSP, not a black-box np.convolve/scipy.signal.fftconvolve call):

        x[n] * h[n]  <-->  X(f) · H(f)

    i.e. convolving two signals in the time domain is IDENTICAL to
    multiplying their spectra in the frequency domain and transforming back:

        y = IDFT( DFT(x) . DFT(h) )

    This is the same y[n] = Σ x[k]·h[n-k] definition as
    discrete_convolution_direct() above — it is mathematically the exact
    same operation, just computed by a different (much faster) route:
    O(P log P) via FFT instead of O(N*M) via nested sums, where
    P = N + M - 1 is the linear-convolution output length.

    We zero-pad both signals to length P = N + M - 1 before transforming
    so that the *circular* convolution the FFT naturally computes equals
    the *linear* convolution we actually want (no wrap-around aliasing).

    Args:
        x: Input signal array
        h: Impulse response array

    Returns:
        Convolved output array of length len(x) + len(h) - 1, matching
        discrete_convolution_direct() sample-for-sample (up to float error).
    """
    N = len(x)
    M = len(h)
    y_len = N + M - 1

    # FFT size: any length >= y_len works for correctness; a power of two
    # (or otherwise "5-smooth") length makes the FFT itself faster.
    fft_len = 1 << (y_len - 1).bit_length()

    X = np.fft.rfft(x, n=fft_len)
    H = np.fft.rfft(h, n=fft_len)
    y_full = np.fft.irfft(X * H, n=fft_len)

    return y_full[:y_len]


def discrete_convolution_reference_slow(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """
    Original literal scalar implementation of y[n] = sum_k x[k]*h[n-k], kept only
    as a reference for correctness-checking discrete_convolution() above (e.g. in
    the oral defense, or to re-verify after any future change). Not called by the
    app — it's the O(N*M) pure-Python version and is too slow for real audio.
    """
    N = len(x)
    M = len(h)
    y_len = N + M - 1
    y = np.zeros(y_len)

    for n in range(y_len):
        for k in range(M):
            if 0 <= n - k < N:
                y[n] += x[n - k] * h[k]

    return y


def create_echo_impulse(delay_samples: int, decay: float, num_echoes: int = 3) -> np.ndarray:
    """
    Create an impulse response for an echo effect.

    Echo is modeled as an LTI system with impulse response:
    h[n] = δ[n] + α·δ[n-D] + α²·δ[n-2D] + α³·δ[n-3D] + ...

    where:
    - δ[n] is the unit impulse (Kronecker delta)
    - D is the delay in samples
    - α is the decay factor (0 < α < 1)

    Args:
        delay_samples: Delay D in samples between echoes
        decay: Decay factor α (0 < α < 1, typically 0.3-0.6)
        num_echoes: Number of echo repetitions

    Returns:
        Impulse response array
    """
    h_len = 1 + num_echoes * delay_samples
    h = np.zeros(h_len)

    # Build impulse response as sum of delayed, decaying impulses
    for i in range(num_echoes + 1):
        idx = i * delay_samples
        if idx < h_len:
            h[idx] = decay ** i  # h[n] = α^i at n = i*D

    return h
