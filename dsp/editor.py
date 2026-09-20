"""
AudioEditor: single-clip editing state (current/original audio, an
undo/redo stack, and a selection range) plus one method per effect,
each of which pushes an undo frame and then delegates to the matching
free function from the sibling dsp modules.

This is the "glue" layer: none of the actual DSP math lives here, only
region-selection bookkeeping (_resolve_region / _apply_in_region) and
undo/redo state around calls into basic_ops / convolution / filters /
dynamics / reverb / repair / hum_removal / speed_silence / noise_reduction.
"""

import numpy as np
from typing import Optional

from .basic_ops import (
    apply_gain, apply_fade, reverse_audio, trim_audio, join_audio,
    normalize_audio, invert_audio,
)
from .convolution import discrete_convolution, create_echo_impulse
from .filters import parametric_eq, multiband_eq
from .dynamics import apply_compressor, apply_distortion, apply_delay, apply_hard_limiter
from .reverb import apply_reverb
from .repair import declick_channel, repair_splice_channel
from .hum_removal import resolve_hum_freq, hum_notch
from .speed_silence import change_speed as _change_speed_fn, remove_silence as _remove_silence_fn
from .noise_reduction import reduce_noise as _reduce_noise_fn


class AudioEditor:
    """
    Manages audio editing state with undo/redo stack.

    Keeps track of:
    - Current edited audio
    - Original audio (for before/after comparison)
    - Undo/redo history
    - Sample rate
    """

    def __init__(self, audio: np.ndarray, sample_rate: int):
        """
        Initialize editor with audio data.

        Args:
            audio: Audio samples (mono or stereo)
            sample_rate: Sample rate in Hz
        """
        self.original = audio.copy()
        self.current = audio.copy()
        self.sample_rate = sample_rate

        # Undo/redo stacks
        self.undo_stack = []
        self.redo_stack = []

        # Selection state
        self.selection_start = 0
        self.selection_end = len(audio)

    @property
    def undo_label(self) -> Optional[str]:
        """
        Human-readable name of the operation Undo would currently
        reverse (e.g. "Apply Fade Out (fx)"), or None if undo_stack is
        empty. Always read fresh off the stack top rather than cached,
        so it can never drift out of sync after an undo/redo/reset --
        surfaced by the Edit menu as "Undo <undo_label>" the same way
        AudioMass names the specific action next to Undo instead of a
        bare "Undo".
        """
        if not self.undo_stack:
            return None
        return self.undo_stack[-1]['label']

    @property
    def redo_label(self) -> Optional[str]:
        """Same as undo_label, but for what Redo would currently re-apply."""
        if not self.redo_stack:
            return None
        return self.redo_stack[-1]['label']

    def _push_undo(self, label: Optional[str] = None):
        """
        Save current state to undo stack.

        Args:
            label: Human-readable name of the operation that is ABOUT TO
                   run (e.g. "Apply Gain (fx)"). Stored on the pushed
                   frame because that is the operation undoing this
                   frame would reverse -- read back out via undo_label
                   above, and by undo()/redo() to report what they just
                   undid/redid.
        """
        self.undo_stack.append({
            'audio': self.current.copy(),
            'selection': (self.selection_start, self.selection_end),
            'label': label
        })
        self.redo_stack.clear()  # Clear redo stack on new operation

    def _resolve_region(self, start_sample: Optional[int] = None,
                         end_sample: Optional[int] = None):
        """
        Resolve which sample range an in-place effect should run over.

        Falls back to self.selection_start/end, and if THAT is empty or
        invalid too, falls back to the whole clip -- matching AudioMass's
        own rule ("if no region, select the whole file") seen in its
        engine.js effect handlers.
        """
        start = self.selection_start if start_sample is None else start_sample
        end = self.selection_end if end_sample is None else end_sample

        total = len(self.current)
        start = max(0, min(int(start), total))
        end = max(0, min(int(end), total))

        if end <= start:
            # No usable selection -> whole clip, exactly like AudioMass
            # auto-selecting start=0, end=duration when no region exists.
            start, end = 0, total

        return start, end

    def _apply_in_region(self, mono_fn, start_sample: Optional[int] = None,
                          end_sample: Optional[int] = None):
        """
        Run a length-preserving mono effect function over only the
        selected sample range, splicing the processed audio back into
        self.current -- everything outside the selection is left
        untouched, exactly like AudioMass applying an FX to a region.

        Args:
            mono_fn: Callable(channel_slice: np.ndarray) -> np.ndarray,
                     same length in as out (e.g. a closure wrapping
                     apply_gain / parametric_eq / apply_compressor /...).
            start_sample, end_sample: Optional explicit sample bounds;
                     defaults to the current selection (or whole clip).
        """
        start, end = self._resolve_region(start_sample, end_sample)

        if self.current.ndim == 1:
            segment = self.current[start:end]
            self.current[start:end] = mono_fn(segment)
        else:
            for ch in range(self.current.shape[1]):
                segment = self.current[start:end, ch]
                self.current[start:end, ch] = mono_fn(segment)

    def undo(self) -> Optional[str]:
        """
        Undo last operation.

        Returns the human-readable label of the operation that was just
        undone (e.g. "Apply Fade Out (fx)"), or None if the undo stack
        was empty and nothing happened. Checking the return value for
        None (rather than truthiness) matters here: a successful undo
        of an unlabeled legacy frame returns None too, which the caller
        should still treat as "undo happened" -- see the Flask route,
        which tracks success separately via the stack-length check.
        """
        if not self.undo_stack:
            return None

        # Save current to redo stack, tagged with the same label -- that
        # label is what a future Redo of this exact frame would re-apply.
        undone_label = self.undo_stack[-1]['label']
        self.redo_stack.append({
            'audio': self.current.copy(),
            'selection': (self.selection_start, self.selection_end),
            'label': undone_label
        })

        # Restore previous state
        state = self.undo_stack.pop()
        self.current = state['audio']
        self.selection_start, self.selection_end = state['selection']
        return undone_label

    def redo(self) -> Optional[str]:
        """
        Redo last undone operation.

        Returns the human-readable label of the operation that was just
        redone (e.g. "Apply Fade Out (fx)"), or None if the redo stack
        was empty and nothing happened.
        """
        if not self.redo_stack:
            return None

        redone_label = self.redo_stack[-1]['label']

        # Save current to undo stack, tagged with the same label -- so a
        # future Undo reports it's undoing this same operation again.
        self.undo_stack.append({
            'audio': self.current.copy(),
            'selection': (self.selection_start, self.selection_end),
            'label': redone_label
        })

        # Restore next state
        state = self.redo_stack.pop()
        self.current = state['audio']
        self.selection_start, self.selection_end = state['selection']
        return redone_label

    # High-level operation methods (each saves undo state)

    def trim(self, start: Optional[int] = None, end: Optional[int] = None):
        """Trim to selection or specified range."""
        self._push_undo(label='Trim to Selection')
        start = start if start is not None else self.selection_start
        end = end if end is not None else self.selection_end
        self.current = trim_audio(self.current, start, end)
        self.selection_start = 0
        self.selection_end = len(self.current)

    def join(self, other_audio: np.ndarray):
        """Join another audio clip to the end."""
        self._push_undo(label='Join Audio')
        self.current = join_audio(self.current, other_audio)
        self.selection_end = len(self.current)

    def reverse(self, selection_only: bool = False,
                start_sample: Optional[int] = None,
                end_sample: Optional[int] = None):
        """
        Reverse entire clip, or just a region.

        start_sample/end_sample let the caller specify exactly which
        region to reverse (matching every other in-place effect method's
        convention via _resolve_region()) instead of relying on
        self.selection_start/end alone -- those only reflect whatever a
        PRIOR request happened to leave behind (e.g. a previous trim),
        not necessarily the region the frontend's user just dragged for
        THIS reverse call. Without this, "Reverse Selection" could
        silently reverse the wrong region, or the whole clip, whenever
        the frontend's live drag-selection hadn't already been pushed
        into backend state by some other route first.
        """
        self._push_undo(label='Reverse Selection' if selection_only else 'Reverse All')
        if selection_only:
            # _resolve_region() falls back to the whole clip when no
            # region is usable, so this always reverses SOMETHING
            # sensible even if start/end were never supplied.
            start, end = self._resolve_region(start_sample, end_sample)
            selected = self.current[start:end]
            reversed_section = reverse_audio(selected)
            self.current[start:end] = reversed_section
        else:
            self.current = reverse_audio(self.current)

    def gain(self, gain_db: float, start_sample: Optional[int] = None,
             end_sample: Optional[int] = None):
        """Apply gain to the selected region (or whole clip if none)."""
        self._push_undo(label='Apply Gain (fx)')
        self._apply_in_region(lambda seg: apply_gain(seg, gain_db),
                               start_sample, end_sample)

    def fade_in(self, duration_sec: float, curve: str = 'cosine',
                start_sample: Optional[int] = None,
                end_sample: Optional[int] = None):
        """Apply fade in at the start of the selected region."""
        self._push_undo(label='Apply Fade In (fx)')
        duration_samples = int(duration_sec * self.sample_rate)
        self._apply_in_region(
            lambda seg: apply_fade(seg, duration_samples, 'in', curve),
            start_sample, end_sample
        )

    def fade_out(self, duration_sec: float, curve: str = 'cosine',
                 start_sample: Optional[int] = None,
                 end_sample: Optional[int] = None):
        """Apply fade out at the end of the selected region."""
        self._push_undo(label='Apply Fade Out (fx)')
        duration_samples = int(duration_sec * self.sample_rate)
        self._apply_in_region(
            lambda seg: apply_fade(seg, duration_samples, 'out', curve),
            start_sample, end_sample
        )

    def echo(self, delay_ms: float, decay: float = 0.5, num_echoes: int = 3,
              start_sample: Optional[int] = None,
              end_sample: Optional[int] = None):
        """
        Apply echo effect using manual convolution, over the selected
        region only.

        This ties directly to LTI system theory:
        - Echo = LTI system with specific impulse response
        - Impulse response = sum of delayed, decaying impulses
        - Output = input convolved with impulse response

        Args:
            delay_ms: Echo delay in milliseconds
            decay: Decay factor (0-1)
            num_echoes: Number of echo repetitions
            start_sample, end_sample: Region to apply to (default: selection)
        """
        self._push_undo(label='Apply Echo (fx)')
        delay_samples = int((delay_ms / 1000.0) * self.sample_rate)
        h = create_echo_impulse(delay_samples, decay, num_echoes)

        def _echo_channel(seg: np.ndarray) -> np.ndarray:
            y = discrete_convolution(seg, h)
            max_val = np.max(np.abs(y))
            if max_val > 1.0:
                y = y / max_val
            return y[:len(seg)]  # truncate back to the region's own length

        self._apply_in_region(_echo_channel, start_sample, end_sample)

    def equalize(self, low_gain_db: float = 0.0, mid_gain_db: float = 0.0,
                 high_gain_db: float = 0.0, low_freq: float = 250.0,
                 mid_freq: float = 1000.0, high_freq: float = 4000.0,
                 q: float = 1.0, start_sample: Optional[int] = None,
                 end_sample: Optional[int] = None):
        """
        Apply 3-band parametric EQ (manual biquad IIR filter chain) to
        the selected region only.

        This ties directly to LTI system theory, same as Echo above,
        but using a recursive (IIR) filter instead of an FIR convolution:
        - Each band = a 2nd-order IIR system (biquad) with its own
          frequency response, tuned by (frequency, gain, Q)
        - Output = input filtered through low -> mid -> high bands in series

        Args:
            low_gain_db, mid_gain_db, high_gain_db: Boost/cut per band (dB)
            low_freq, mid_freq, high_freq: Center frequency per band (Hz)
            q: Quality factor (bandwidth), shared across all three bands
            start_sample, end_sample: Region to apply to (default: selection)
        """
        self._push_undo(label='Apply 3-Band EQ (fx)')
        self._apply_in_region(
            lambda seg: parametric_eq(
                seg, self.sample_rate,
                low_gain_db, mid_gain_db, high_gain_db,
                low_freq, mid_freq, high_freq, q
            ),
            start_sample, end_sample
        )

    def multiband_equalize(self, bands: list, start_sample: Optional[int] = None,
                            end_sample: Optional[int] = None,
                            label: str = 'Apply EQ (fx)'):
        """
        Apply an arbitrary-length chain of biquad EQ bands to the
        selected region only -- the shared engine behind Paragraphic EQ
        (a handful of user-placed bands of mixed types: highpass /
        lowpass / peaking) and Graphic EQ / Graphic EQ (20 bands) (a
        fixed ladder of lowshelf + peaking + highshelf bands, one per
        fader). See multiband_eq() for the full derivation (fused
        cascade of second-order sections, one pass over the samples).

        Args:
            bands: List of dicts, each with keys 'type', 'freq', 'gain',
                'q', and optional 'on' (see multiband_eq() docstring)
            start_sample, end_sample: Region to apply to (default: selection)
            label: Which panel called this shared engine -- e.g. "Apply
                Paragraphic EQ (fx)" or "Apply Graphic EQ (fx)". The
                route can't infer this from `bands` alone (all three
                panels send the same shape), so the frontend passes it
                through the request body; see app.py's multiband_eq_route.
        """
        self._push_undo(label=label)
        self._apply_in_region(
            lambda seg: multiband_eq(seg, self.sample_rate, bands),
            start_sample, end_sample
        )

    def compress(self, threshold_db: float = -24.0, ratio: float = 4.0,
                 knee_db: float = 6.0, attack_ms: float = 5.0,
                 release_ms: float = 100.0, makeup_gain_db: float = 0.0,
                 start_sample: Optional[int] = None,
                 end_sample: Optional[int] = None):
        """
        Apply dynamic range compression (manual soft-knee compressor) to
        the selected region only.

        Reduces the volume of parts of the signal above `threshold_db`,
        smoothing the gain change over time using attack/release times.
        See apply_compressor() above for the full derivation.

        Args:
            threshold_db: Level (dB) above which compression starts
            ratio: Compression ratio, e.g. 4.0 means 4:1
            knee_db: Width of the soft-knee transition in dB
            attack_ms: Time (ms) for gain reduction to engage
            release_ms: Time (ms) for gain reduction to release
            makeup_gain_db: Additional gain applied after compression
            start_sample, end_sample: Region to apply to (default: selection)
        """
        self._push_undo(label='Apply Compressor (fx)')
        self._apply_in_region(
            lambda seg: apply_compressor(
                seg, self.sample_rate,
                threshold_db, ratio, knee_db, attack_ms, release_ms,
                makeup_gain_db
            ),
            start_sample, end_sample
        )

    def reverb(self, duration_s: float = 1.5, decay: float = 2.0,
               mix: float = 0.3, reverse: bool = False,
               seed: Optional[int] = None,
               start_sample: Optional[int] = None,
               end_sample: Optional[int] = None):
        """
        Apply convolution reverb using manual convolution, over the
        selected region only.

        This ties directly to LTI system theory, same as Echo above:
        - Reverb = LTI system with a dense, noise-based impulse response
          (vs. Echo's sparse train of a few discrete decaying spikes)
        - Output = input convolved with impulse response, mixed with dry

        Args:
            duration_s: Reverb tail length in seconds ("room size")
            decay: Decay exponent (higher = shorter/tighter decay)
            mix: Wet/dry mix, 0.0 = fully dry, 1.0 = fully wet
            reverse: If True, produces a reverse-reverb swell
            seed: Optional random seed for reproducible impulse response
            start_sample, end_sample: Region to apply to (default: selection)
        """
        self._push_undo(label='Apply Reverb (fx)')
        start, end = self._resolve_region(start_sample, end_sample)

        if self.current.ndim == 1:
            segment = self.current[start:end]
            self.current[start:end] = apply_reverb(
                segment, self.sample_rate, duration_s, decay, mix, reverse, seed
            )
        else:
            # Stereo: reverb each channel independently (each gets its
            # own random impulse for a wider stereo image, matching
            # AudioMass's approach of separate L/R impulse buffers)
            seed_l = seed
            seed_r = None if seed is None else seed + 1
            seeds = [seed_l, seed_r] + [
                (None if seed is None else seed + 2 + ch)
                for ch in range(2, self.current.shape[1])
            ]
            for ch in range(self.current.shape[1]):
                segment = self.current[start:end, ch]
                self.current[start:end, ch] = apply_reverb(
                    segment, self.sample_rate,
                    duration_s, decay, mix, reverse, seeds[ch]
                )

    def normalize(self, target_db: float = -1.0, mode: str = 'peak',
                  start_sample: Optional[int] = None,
                  end_sample: Optional[int] = None):
        """Normalize the selected region to a target peak/RMS level (see normalize_audio())."""
        self._push_undo(label='Apply Normalize (fx)')
        self._apply_in_region(
            lambda seg: normalize_audio(seg, target_db, mode),
            start_sample, end_sample
        )

    def invert(self, start_sample: Optional[int] = None,
               end_sample: Optional[int] = None):
        """Flip polarity of the selected region: y[n] = -x[n] (see invert_audio())."""
        self._push_undo(label='Apply Invert (fx)')
        self._apply_in_region(invert_audio, start_sample, end_sample)

    def distort(self, drive_db: float = 12.0, mode: str = 'soft',
                start_sample: Optional[int] = None,
                end_sample: Optional[int] = None):
        """Apply waveshaping distortion to the selected region (see apply_distortion())."""
        self._push_undo(label='Apply Distortion (fx)')
        self._apply_in_region(
            lambda seg: apply_distortion(seg, drive_db, mode),
            start_sample, end_sample
        )

    def delay(self, delay_ms: float = 300.0, feedback: float = 0.0,
              mix: float = 0.5, start_sample: Optional[int] = None,
              end_sample: Optional[int] = None):
        """
        Apply a single-tap (optionally feedback) delay line to the
        selected region only.

        Manual sample-index recursion, distinct from Echo's
        convolution-based approach -- see apply_delay() for the
        derivation and the contrast with create_echo_impulse().
        """
        self._push_undo(label='Apply Delay (fx)')
        self._apply_in_region(
            lambda seg: apply_delay(seg, self.sample_rate, delay_ms, feedback, mix),
            start_sample, end_sample
        )

    def limit(self, ceiling_db: float = -0.3, release_ms: float = 50.0,
              start_sample: Optional[int] = None,
              end_sample: Optional[int] = None):
        """Apply brickwall limiting to the selected region (see apply_hard_limiter())."""
        self._push_undo(label='Apply Hard Limiter (fx)')
        self._apply_in_region(
            lambda seg: apply_hard_limiter(seg, self.sample_rate, ceiling_db, release_ms),
            start_sample, end_sample
        )

    def change_speed(self, speed_factor: float = 1.0):
        """
        Change speed/pitch together via resampling (see
        change_speed() module function). Alters clip duration, so
        selection bounds are reset to the full (new) length.
        """
        self._push_undo(label='Apply Speed / Pitch (fx)')
        self.current = _change_speed_fn(self.current, speed_factor)
        self.selection_start = 0
        self.selection_end = len(self.current)

    def remove_silence(self, threshold_db: float = -40.0,
                        min_silence_ms: float = 300.0,
                        padding_ms: float = 50.0):
        """
        Shorten long silent gaps (see remove_silence() module
        function). Alters clip duration, so selection bounds are
        reset to the full (new) length.
        """
        self._push_undo(label='Remove Silence (fx)')
        self.current = _remove_silence_fn(
            self.current, self.sample_rate,
            threshold_db, min_silence_ms, padding_ms
        )
        self.selection_start = 0
        self.selection_end = len(self.current)

    def reduce_noise(self, noise_sample_s: float = 0.5,
                      reduction_db: float = 12.0, frame_size: int = 2048):
        """
        Apply STFT-based spectral-subtraction denoising (see
        reduce_noise() module function for the full derivation).
        """
        self._push_undo(label='Noise Reduction (fx)')
        self.current = _reduce_noise_fn(
            self.current, self.sample_rate,
            noise_sample_s, reduction_db, frame_size
        )

    def declick(self, sensitivity: str = 'medium',
                start_sample: Optional[int] = None,
                end_sample: Optional[int] = None) -> int:
        """
        Audio Repair -> Click Reduction: detect and smooth over short
        transient clicks in the selected region (see declick_channel()).

        Returns the total number of clicks fixed across all channels.
        """
        self._push_undo(label='Click Reduction (fx)')
        start, end = self._resolve_region(start_sample, end_sample)
        total_fixed = 0

        if self.current.ndim == 1:
            segment = self.current[start:end]
            repaired, count = declick_channel(segment, self.sample_rate, sensitivity)
            self.current[start:end] = repaired
            total_fixed += count
        else:
            for ch in range(self.current.shape[1]):
                segment = self.current[start:end, ch]
                repaired, count = declick_channel(segment, self.sample_rate, sensitivity)
                self.current[start:end, ch] = repaired
                total_fixed += count

        return total_fixed

    def repair_edit(self, sensitivity: str = 'medium',
                     start_sample: Optional[int] = None,
                     end_sample: Optional[int] = None) -> int:
        """
        Audio Repair -> Edit Repair: detect and smooth over abrupt
        edit-point discontinuities/splices in the selected region (see
        repair_splice_channel()).

        Returns the total number of splices fixed across all channels.
        """
        self._push_undo(label='Edit Repair (fx)')
        start, end = self._resolve_region(start_sample, end_sample)
        total_fixed = 0

        if self.current.ndim == 1:
            segment = self.current[start:end]
            repaired, count = repair_splice_channel(segment, self.sample_rate, sensitivity)
            self.current[start:end] = repaired
            total_fixed += count
        else:
            for ch in range(self.current.shape[1]):
                segment = self.current[start:end, ch]
                repaired, count = repair_splice_channel(segment, self.sample_rate, sensitivity)
                self.current[start:end, ch] = repaired
                total_fixed += count

        return total_fixed

    def hum_reduce(self, mode='auto', harmonics: int = 8, q: float = 12.0,
                    start_sample: Optional[int] = None,
                    end_sample: Optional[int] = None) -> float:
        """
        Audio Repair -> Hum Reduction: detect (or use a forced) mains
        hum frequency and notch it plus its harmonics out of the
        selected region (see resolve_hum_freq() / hum_notch()).

        Detection always looks at channel 0 of the selected region (an
        electrical hum is typically present equally on all channels), and
        the SAME detected frequency is then notched from every channel.

        Returns the hum frequency that was detected/used, in Hz.
        """
        self._push_undo(label='Hum Reduction (fx)')
        start, end = self._resolve_region(start_sample, end_sample)

        detect_source = self.current[start:end] if self.current.ndim == 1 else self.current[start:end, 0]
        freq = resolve_hum_freq(detect_source, self.sample_rate, mode)

        self._apply_in_region(
            lambda seg: hum_notch(seg, self.sample_rate, freq, harmonics, q),
            start_sample, end_sample
        )

        return freq

    def reset_to_original(self):
        """Reset to original loaded audio."""
        self._push_undo(label='Reset to Original')
        self.current = self.original.copy()
        self.selection_start = 0
        self.selection_end = len(self.current)

