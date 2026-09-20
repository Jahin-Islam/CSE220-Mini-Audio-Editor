"""
Mini Audio Editor - Core DSP Package
CSE220 Signals and Linear Systems Project

This package contains MANUAL implementations of core DSP operations,
split into one focused module per topic instead of one large file:

    convolution.py      discrete convolution (direct + FFT) & echo impulse
    basic_ops.py         gain, fade, reverse, normalize, invert, trim, join
    filters.py            biquad coefficients/recursion, peaking/parametric/
                          multiband EQ
    dynamics.py           compressor, hard limiter, distortion, delay
    reverb.py             convolution reverb (impulse + convolution.py)
    repair.py              click reduction & edit-splice repair (Hermite
                          bridge)
    hum_removal.py         mains-hum detection (Goertzel) & notch filtering
    speed_silence.py       speed/pitch change, silence trimming
    noise_reduction.py     STFT spectral-subtraction denoising
    mixing.py               multi-track-to-stereo mixdown
    editor.py                AudioEditor: undo/redo + selection state around
                          all of the above
    track.py                  Track / MultiTrackSession: multi-track project
                          state built on top of AudioEditor

No library shortcuts are used for convolution, gain, fade, reverse,
filtering, compression, or any other operation described as "manual" in
each module's own docstring — every one is implemented from its
mathematical definition, for course credit / oral defense.

Everything below is re-exported here so callers can do either:

    from dsp import AudioEditor, MultiTrackSession
    from dsp.filters import multiband_eq

i.e. the flat `dsp.<name>` surface below is a convenience for the most
commonly used pieces; anything not listed here can still be reached via
its own submodule.
"""

from .convolution import (
    discrete_convolution_direct,
    discrete_convolution,
    discrete_convolution_reference_slow,
    create_echo_impulse,
)
from .basic_ops import (
    apply_gain,
    apply_fade,
    reverse_audio,
    normalize_audio,
    invert_audio,
    trim_audio,
    join_audio,
)
from .filters import (
    biquad_coefficients,
    biquad_apply,
    biquad_peaking_filter,
    parametric_eq,
    multiband_eq,
)
from .dynamics import (
    apply_compressor,
    apply_hard_limiter,
    apply_distortion,
    apply_delay,
)
from .reverb import (
    create_reverb_impulse,
    apply_reverb,
)
from .repair import (
    declick_channel,
    repair_splice_channel,
)
from .hum_removal import (
    goertzel_magnitude,
    resolve_hum_freq,
    hum_notch,
)
from .speed_silence import (
    change_speed,
    remove_silence,
)
from .noise_reduction import (
    reduce_noise,
)
from .mixing import (
    mix_tracks_to_stereo,
)
from .editor import AudioEditor
from .track import Track, MultiTrackSession, DEFAULT_TRACK_COLORS

__all__ = [
    'discrete_convolution_direct', 'discrete_convolution',
    'discrete_convolution_reference_slow', 'create_echo_impulse',
    'apply_gain', 'apply_fade', 'reverse_audio', 'normalize_audio',
    'invert_audio', 'trim_audio', 'join_audio',
    'biquad_coefficients', 'biquad_apply', 'biquad_peaking_filter',
    'parametric_eq', 'multiband_eq',
    'apply_compressor', 'apply_hard_limiter', 'apply_distortion', 'apply_delay',
    'create_reverb_impulse', 'apply_reverb',
    'declick_channel', 'repair_splice_channel',
    'goertzel_magnitude', 'resolve_hum_freq', 'hum_notch',
    'change_speed', 'remove_silence', 'reduce_noise',
    'mix_tracks_to_stereo',
    'AudioEditor', 'Track', 'MultiTrackSession', 'DEFAULT_TRACK_COLORS',
]
