"""
Multi-track-to-stereo mixdown.

- _to_stereo: upmix mono -> stereo by channel duplication, so tracks of
  different channel counts can be summed together.
- mix_tracks_to_stereo: places each track on the shared timeline at its
  own start_sample, sums them (superposition), then runs the result
  through dynamics.apply_hard_limiter() as a mix-bus safety limiter.
"""

import numpy as np

from .dynamics import apply_hard_limiter

def _to_stereo(audio: np.ndarray) -> np.ndarray:
    """
    Upmix mono audio to stereo by duplicating the single channel into
    both L and R; leaves already-stereo audio unchanged.

    Used by mix_tracks_to_stereo() below to reconcile tracks of
    different channel counts before summing them -- e.g. a mono
    voiceover track mixed against a stereo music bed. Duplication
    (rather than, say, panning mono hard to one side) is the standard
    convention: it puts the mono source at the same perceived center
    position a stereo signal's shared content would occupy.
    """
    if audio.ndim == 2:
        return audio
    return np.column_stack([audio, audio])


def mix_tracks_to_stereo(tracks: list, sample_rate: int,
                          ceiling_db: float = -0.3) -> np.ndarray:
    """
    Mix multiple independently-timed audio tracks down to a single
    stereo output -- the DSP core of multi-track playback/export.

    Manual derivation, in three stages:

    1. TIMELINE PLACEMENT. Each track carries its own
       start_sample (>= 0), the offset in the shared timeline at which
       its audio begins -- everything before that offset is silence.
       This is literally a shifted unit-step multiplying each track's
       signal: track_i placed at offset d_i contributes
           x_i[n - d_i] * u[n - d_i]
       to the timeline, where u[.] is the unit step (zero for negative
       indices). The output timeline's length is therefore
           N = max_i(d_i + len(x_i))
       i.e. exactly long enough to hold the latest-ending track and no
       longer -- matching how a real multitrack timeline auto-extends
       to fit its content rather than needing a pre-set fixed length.

    2. SUMMATION. Mixing is literally y[n] = sum_i(x_i[n - d_i]) --
       superposition of the (now timeline-aligned, zero-padded) per-track
       signals. This is the entire "combine tracks" operation; there is
       no other processing here by design, so per-track effects (gain,
       EQ, reverb, ...) already baked into each track's own audio by
       AudioEditor before this function ever sees it are exactly what
       comes through, unmodified in relative balance.

    3. HEADROOM. Summing N independent signals raises peak level
       (worst case N times, though real material rarely hits that since
       peaks in different tracks rarely align in phase and magnitude
       simultaneously) -- left unmanaged, a mix of several
       already-near-0dBFS tracks reliably introduces sample clipping the
       naive sum-then-hope approach can't prevent. apply_hard_limiter()
       (see its own docstring for the peak-envelope-follower derivation)
       is reused here exactly as intended -- a mix bus limiter is the
       textbook use case for a limiter, catching only the specific
       samples where the SUM exceeds ceiling_db, smoothly, rather than
       flattening the whole mix's dynamics the way a blanket
       normalize-by-peak pass would (turning every sample down uniformly
       because of one loud moment, even in tracks that never got loud).

    Args:
        tracks: List of dicts, each {'audio': np.ndarray, 'start_sample': int}.
            'audio' may be mono (n,) or stereo (n, 2) -- mono tracks are
            upmixed to stereo (see _to_stereo()) so every track
            contributes at the same relative center position regardless
            of its own channel count. 'start_sample' must be >= 0 --
            tracks always start at or after timeline zero (unlike a
            single-track selection, which can encode "no selection" as
            a negative/absent value elsewhere in this codebase, a
            timeline offset has no analogous default-to-something-else
            case: an unset offset is just 0, "starts at the top").
        sample_rate: Sample rate in Hz, shared by all tracks (mixing
            tracks at different sample rates would require resampling
            first, which is out of scope here -- every track in this
            app is always recorded/loaded at the session's rate).
        ceiling_db: Final mix's peak ceiling in dBFS, passed straight
            through to apply_hard_limiter().

    Returns:
        Stereo (n, 2) float32 array, peak <= ceiling_db. Empty (0, 2)
        if tracks is empty or every track's audio has zero length.
    """
    if not tracks:
        return np.zeros((0, 2), dtype=np.float32)

    total_length = 0
    for t in tracks:
        start = max(0, int(t['start_sample']))
        total_length = max(total_length, start + len(t['audio']))

    if total_length == 0:
        return np.zeros((0, 2), dtype=np.float32)

    mix = np.zeros((total_length, 2), dtype=np.float64)

    for t in tracks:
        start = max(0, int(t['start_sample']))
        audio = _to_stereo(t['audio'])
        end = start + len(audio)
        mix[start:end] += audio

    limited = apply_hard_limiter(mix.astype(np.float32), sample_rate, ceiling_db)
    return limited.astype(np.float32)
