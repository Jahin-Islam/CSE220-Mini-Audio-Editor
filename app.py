"""
Mini Audio Editor - Flask Backend
CSE220 Signals and Linear Systems Project

Flask server that handles:
- Audio file upload/download
- DSP operations via the dsp package
- Playback state management
- Undo/redo operations
"""

from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import numpy as np
import soundfile as sf
import io
import os
import base64
from dsp import AudioEditor, MultiTrackSession

app = Flask(__name__)
CORS(app)

# The whole app's state now lives in one MultiTrackSession rather than a
# single global AudioEditor -- see dsp/track.py's MultiTrackSession/Track
# docstrings for the reasoning. A single-file edit is simply a session
# with exactly one track; there is no separate single-track code path.
# session_sample_rate is None until the first track is ever added, since
# MultiTrackSession needs a sample rate up front but nothing has been
# uploaded yet at server startup.
session: MultiTrackSession = None


def get_track_or_error(track_id: str):
    """
    Resolve a Track by id, shared by every per-track route below.

    Takes the track_id itself (not a whole request dict) so each route
    can extract it however fits its own HTTP method -- data.get('trackId')
    for POST routes with a JSON body, request.args.get('trackId') for the
    three GET routes (get_original/export/get_audio_data), which can't
    carry a JSON body the same way.

    Returns (track, None) on success, or (None, (response, status)) on
    failure -- the caller does
        track, err = get_track_or_error(track_id)
        if err:
            return err
    which reads the same way as this file's existing
    "if editor_instance is None: return jsonify(...), 400" checks did,
    just resolving a specific track instead of the one-and-only global.

    Two distinct failure modes, both worth telling apart in the error
    message (a person debugging "why did my request fail" benefits from
    knowing which): no session exists yet at all (nothing has ever been
    uploaded), vs a session exists but this specific trackId isn't in it
    (stale/typo'd ID, or a track that's since been removed).
    """
    if session is None:
        return None, (jsonify({'error': 'No audio loaded'}), 400)

    if not track_id:
        return None, (jsonify({'error': 'trackId is required'}), 400)

    track = session.get_track(track_id)
    if track is None:
        return None, (jsonify({'error': f'No track with id {track_id}'}), 404)

    return track, None

# --- Convolution cost guard (Echo / Reverb) ---
# discrete_convolution() computes the same y[n] = sum_k x[k]*h[n-k]
# definition as a direct O(N*M) sum, but via the Convolution Theorem
# (FFT multiply + inverse FFT) — see dsp/convolution.py discrete_convolution
# for the derivation. That makes it O(P log P), P = N+M-1, not O(N*M).
#
# Benchmarked throughput (see dsp/mixing.py docstring / project notes) is
# roughly ~9e7 (P*log2(P)) units/sec on typical hardware. Requests
# estimated to exceed CONVOLUTION_TIME_LIMIT_SEC are rejected up front
# with the estimated wait, instead of silently running for a long time.
# In practice this guard should essentially never trigger anymore for
# reasonable audio lengths (a 3-minute clip with a 1.5s reverb tail
# takes ~1-2 seconds) -- it now exists purely as a sanity backstop
# against pathological inputs (e.g. an extremely long impulse), not as
# a normal-use limiter the way the old O(N*M) estimate was.
CONVOLUTION_UNITS_PER_SEC = 45_000_000
CONVOLUTION_TIME_LIMIT_SEC = 20.0

# Biquad-cascade jobs (Graphic EQ, Paragraphic EQ, Hum Reduction) are
# legitimately slower per second of audio than FFT-based convolution,
# so a full-length track with several active bands can take over a
# minute even though it's ordinary, not pathological, usage (e.g. a
# 10-band Graphic EQ over a full 3+ minute stereo song is ~80s). Give
# these their own, longer ceiling so normal full-track edits go
# through instead of being rejected outright -- CONVOLUTION_TIME_LIMIT_SEC
# stays tight for Echo/Reverb, where anything over ~20s really is an
# extreme input (see estimate_convolution_seconds above).
BIQUAD_CASCADE_TIME_LIMIT_SEC = 150.0

# --- Biquad-cascade cost guard (Graphic EQ / Paragraphic EQ / Hum Reduction) ---
# multiband_eq()'s cascade is a sequential per-sample Python loop (the
# recursion can't be FFT-accelerated like discrete_convolution above),
# so its cost scales with region length x active bands x channels.
#
# This constant is measured, not guessed: benchmarked at ~0.0195s of
# wall-clock time per second of audio per active band per channel,
# stable across region lengths from 5s up to 200+s (verified directly
# against this app's own multiband_eq() on this reference hardware).
MULTIBAND_EQ_SEC_PER_BAND_SECOND = 0.02


def estimate_convolution_seconds(signal_length: int, impulse_length: int) -> float:
    """Estimate wall-clock time for discrete_convolution() (FFT-based),
    from the measured throughput above. Used to warn/reject before
    running a convolution that would take unreasonably long."""
    p = signal_length + impulse_length - 1
    if p < 2:
        return 0.0
    units = p * np.log2(p)
    return units / CONVOLUTION_UNITS_PER_SEC


def resolve_selection_samples(data: dict, sample_rate: int):
    """
    Read an optional {'start': seconds, 'end': seconds} selection out of
    a request's JSON body and convert to sample indices.

    Every in-place effect route accepts this so effects apply only to
    the user's current waveform selection (matching AudioMass, which
    always applies FX to 'the region', defaulting to the whole file if
    none is selected) instead of always processing the entire clip.

    sample_rate is passed in explicitly (the calling route's own
    track.editor.sample_rate) rather than read off a global -- this
    helper doesn't need to know which track it's serving, just what
    rate to convert seconds at, so it stays a small pure function
    instead of being implicitly coupled to "the current track".

    Returns (start_sample, end_sample) as ints, or (None, None) if no
    selection was sent -- AudioEditor's own _resolve_region() then falls
    back to its tracked self.selection_start/end, and finally to the
    whole clip if that is empty too.
    """
    start_s = data.get('start', None)
    end_s = data.get('end', None)

    if start_s is None and end_s is None:
        return None, None

    start_sample = int(round(float(start_s) * sample_rate)) if start_s is not None else None
    end_sample = int(round(float(end_s) * sample_rate)) if end_s is not None else None
    return start_sample, end_sample


@app.route('/')
def index():
    """Serve the main editor interface."""
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def upload_audio():
    """
    Upload an audio file as a NEW TRACK in the session.

    The first-ever upload creates the session itself (fixing its
    sample_rate for every track that follows); every upload after that
    adds another track alongside the existing ones rather than
    replacing them -- multi-track mashups are the point, so loading a
    second file needs to ADD to the session, not discard the first
    track the way a single global editor_instance used to.

    A later upload at a DIFFERENT sample rate than the session's is
    rejected rather than silently resampled or silently mixed wrong --
    see mix_tracks_to_stereo()'s docstring on why cross-rate mixing
    isn't attempted. Matching the session's rate (e.g. via a proper
    resampling feature) is a real, separate piece of work, not
    something to fold in here as a side effect of upload.

    Returns JSON with the new track's id/summary plus the same
    waveform/duration/etc fields as before (now describing just this
    one new track, not "the" audio, since there can be several).
    """
    global session

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        file_content = file.read()
        audio_data, sample_rate = sf.read(io.BytesIO(file_content))

        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        if session is None:
            session = MultiTrackSession(int(sample_rate))
        elif int(sample_rate) != session.sample_rate:
            return jsonify({
                'error': (
                    f'This file is {int(sample_rate)} Hz, but the session is '
                    f'{session.sample_rate} Hz (set by the first track loaded). '
                    f'Mixing different sample rates together needs resampling, '
                    f'which isn\'t supported yet.'
                )
            }), 400

        # Derive a display name from the filename (minus extension) so
        # the track list shows "guitar" rather than a generic "Track 3"
        # when the person's file already has a meaningful name.
        raw_name = os.path.splitext(file.filename)[0].strip()
        track_name = raw_name if raw_name else None

        track = session.add_track(audio_data, name=track_name)

        waveform = prepare_waveform(audio_data)

        return jsonify({
            'success': True,
            'track': track.to_summary_dict(),
            'waveform': waveform,
            'duration': len(audio_data) / sample_rate,
            'sample_rate': int(sample_rate),
            'channels': 1 if audio_data.ndim == 1 else audio_data.shape[1],
            'samples': len(audio_data),
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[ERROR] Upload failed: {str(e)}")
        print(f"[ERROR] Traceback:\n{error_details}")
        return jsonify({'error': str(e), 'details': error_details}), 500


@app.route('/api/join', methods=['POST'])
def join_audio():
    """Join a second audio file onto the end of one existing track's own clip."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    # multipart/form-data (this route uploads a file), so trackId comes
    # from the form fields alongside it, not a JSON body.
    track, err = get_track_or_error(request.form.get('trackId'))
    if err:
        return err

    try:
        file = request.files['file']
        audio_data, sample_rate = sf.read(io.BytesIO(file.read()))

        # Ensure sample rates match
        if sample_rate != track.editor.sample_rate:
            return jsonify({'error': f'Sample rate mismatch: {sample_rate} vs {track.editor.sample_rate}'}), 400

        # Convert to float32
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        # Match channel count (convert to mono or stereo as needed)
        audio_data = match_channels(audio_data, track.editor.current)

        track.editor.join(audio_data)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'duration': len(track.editor.current) / track.editor.sample_rate,
            'samples': len(track.editor.current),
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/trim', methods=['POST'])
def trim():
    """Trim one track's own clip to its selected region."""
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        start_sample = int(data.get('start', 0))
        end_sample = int(data.get('end', len(track.editor.current)))

        track.editor.trim(start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'duration': len(track.editor.current) / track.editor.sample_rate,
            'samples': len(track.editor.current),
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reverse', methods=['POST'])
def reverse():
    """Reverse one track's own clip (entire clip or selection)."""
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        selection_only = data.get('selectionOnly', False)
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        track.editor.reverse(selection_only, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gain', methods=['POST'])
def gain():
    """Apply gain/volume scaling to one track's own clip."""
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        gain_db = float(data.get('gainDb', 0))
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        track.editor.gain(gain_db, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/fade', methods=['POST'])
def fade():
    """Apply fade in or fade out to one track's own clip."""
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        fade_type = data.get('type', 'in')  # 'in' or 'out'
        duration_sec = float(data.get('duration', 0.5))
        curve = data.get('curve', 'cosine')  # 'linear' or 'cosine'
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        if fade_type == 'in':
            track.editor.fade_in(duration_sec, curve, start_sample, end_sample)
        else:
            track.editor.fade_out(duration_sec, curve, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/echo', methods=['POST'])
def echo():
    """
    Apply echo effect using manual convolution, to one track's own clip.

    This is the convolution-based DSP operation required for the course.
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        delay_ms = float(data.get('delayMs', 200))
        decay = float(data.get('decay', 0.5))
        num_echoes = int(data.get('numEchoes', 3))
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        # Estimate cost before running: same h_len formula as
        # create_echo_impulse() in dsp/convolution.py. Use the REGION length
        # (what will actually be convolved), not the whole clip.
        delay_samples = int((delay_ms / 1000.0) * track.editor.sample_rate)
        impulse_length = 1 + num_echoes * delay_samples
        region_start, region_end = track.editor._resolve_region(start_sample, end_sample)
        signal_length = region_end - region_start
        est_seconds = estimate_convolution_seconds(signal_length, impulse_length)

        if est_seconds > CONVOLUTION_TIME_LIMIT_SEC:
            return jsonify({
                'error': (
                    f'This would take about {est_seconds:.0f} seconds to process '
                    f'(selection is {signal_length / track.editor.sample_rate:.1f}s long). '
                    f'Try a shorter delay, fewer echoes, or a shorter selection.'
                ),
                'estimatedSeconds': round(est_seconds, 1)
            }), 400

        track.editor.echo(delay_ms, decay, num_echoes, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/equalize', methods=['POST'])
def equalize():
    """
    Apply 3-band parametric EQ using manual biquad IIR filters, to one
    track's own clip.

    Feature-parity addition: matches AudioMass's ParametricEQ effect,
    implemented here as manual DSP (see dsp.filters.parametric_eq).
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        low_gain_db = float(data.get('lowGainDb', 0.0))
        mid_gain_db = float(data.get('midGainDb', 0.0))
        high_gain_db = float(data.get('highGainDb', 0.0))
        low_freq = float(data.get('lowFreq', 250.0))
        mid_freq = float(data.get('midFreq', 1000.0))
        high_freq = float(data.get('highFreq', 4000.0))
        q = float(data.get('q', 1.0))
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        track.editor.equalize(
            low_gain_db, mid_gain_db, high_gain_db,
            low_freq, mid_freq, high_freq, q,
            start_sample, end_sample
        )

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/multiband_eq', methods=['POST'])
def multiband_eq_route():
    """
    Apply an arbitrary-length chain of biquad EQ bands.

    Single shared route behind THREE panels in the UI:
      - Paragraphic EQ: a handful of user-placed bands, mixed types
        (highpass / lowpass / peaking), sent as-is from the node editor.
      - Graphic EQ (10 bands) / Graphic EQ (20 bands): a fixed ladder of
        lowshelf + peaking + highshelf bands (one per fader), built
        client-side from the fader values before being sent here.

    All three ultimately just POST a `bands` list; see
    dsp.filters.multiband_eq for the shared engine (fused cascade of
    second-order sections) and dsp.filters.biquad_coefficients for the
    per-band filter math (matches AudioMass's own use of native
    BiquadFilterNode chains for these same three panels).

    Body: {
        "bands": [
            {"type": "peaking"|"highpass"|"lowpass"|"lowshelf"|"highshelf",
             "freq": <Hz>, "gain": <dB>, "q": <float>, "on": <bool, optional>},
            ...
        ],
        "start": <seconds, optional>, "end": <seconds, optional>
    }
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        raw_bands = data.get('bands', [])
        if not isinstance(raw_bands, list):
            return jsonify({'error': 'bands must be a list'}), 400
        if len(raw_bands) > 32:
            return jsonify({'error': 'Too many EQ bands (max 32)'}), 400

        # This route sits behind three different panels that all send
        # the exact same {bands: [...]} shape (see the route's own
        # docstring above), so multiband_equalize() alone can't tell
        # them apart for the Edit menu's "Undo <name>" label -- the
        # frontend tells us which panel it was called from instead.
        # Whitelisted (not just any client string) so the undo-history
        # label always matches one of the panel names actually shown
        # in the Effects menu.
        EQ_PANEL_LABELS = {
            'paragraphic-eq': 'Apply Paragraphic EQ (fx)',
            'graphic-eq': 'Apply Graphic EQ (fx)',
            'graphic-eq-20': 'Apply Graphic EQ (20 bands) (fx)',
        }
        action_label = EQ_PANEL_LABELS.get(data.get('panel'), 'Apply EQ (fx)')

        valid_types = {'peaking', 'highpass', 'lowpass', 'lowshelf', 'highshelf', 'notch'}
        bands = []
        for b in raw_bands:
            btype = b.get('type', 'peaking')
            if btype not in valid_types:
                return jsonify({'error': f'Unknown band type: {btype}'}), 400
            bands.append({
                'type': btype,
                'freq': float(b.get('freq', 1000.0)),
                'gain': float(b.get('gain', 0.0)),
                'q': float(b.get('q', 1.0)),
                'on': bool(b.get('on', True)),
            })

        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        # Cost guard: multiband_eq's cascade is Python-loop-bound (not
        # FFT-accelerated), so a long region with many active bands can
        # be slow -- same rationale as the Hum Reduction guard above.
        #
        # MULTIBAND_EQ_SEC_PER_BAND_SECOND is a measured constant (not a
        # guess): benchmarked at ~0.0195s of processing per second of
        # audio per active band per channel, stable across region
        # lengths from 5s to 200+s. An earlier version of this guard
        # used an uncalibrated placeholder (0.16) that overestimated
        # cost by roughly 8x, rejecting requests that would actually
        # have finished in well under a minute.
        region_start, region_end = track.editor._resolve_region(start_sample, end_sample)
        region_seconds = (region_end - region_start) / track.editor.sample_rate
        num_channels = 1 if track.editor.current.ndim == 1 else track.editor.current.shape[1]
        active_bands = sum(
            1 for b in bands
            if b['on'] and (b['type'] in ('highpass', 'lowpass', 'notch') or b['gain'] != 0.0)
        )
        est_seconds = region_seconds * max(active_bands, 1) * num_channels * MULTIBAND_EQ_SEC_PER_BAND_SECOND
        if est_seconds > BIQUAD_CASCADE_TIME_LIMIT_SEC:
            return jsonify({
                'error': (
                    f'This would take about {est_seconds:.0f} seconds to process '
                    f'(selection is {region_seconds:.1f}s long with {active_bands} active bands). '
                    f'Try fewer active bands or a shorter selection.'
                ),
                'estimatedSeconds': round(est_seconds, 1)
            }), 400

        track.editor.multiband_equalize(bands, start_sample, end_sample, label=action_label)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/compress', methods=['POST'])
def compress():
    """
    Apply dynamic range compression using a manual soft-knee compressor.

    Feature-parity addition: matches AudioMass's Compressor effect,
    implemented here as manual DSP (see dsp.dynamics.apply_compressor).
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        threshold_db = float(data.get('thresholdDb', -24.0))
        ratio = float(data.get('ratio', 4.0))
        knee_db = float(data.get('kneeDb', 6.0))
        attack_ms = float(data.get('attackMs', 5.0))
        release_ms = float(data.get('releaseMs', 100.0))
        makeup_gain_db = float(data.get('makeupGainDb', 0.0))
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        track.editor.compress(
            threshold_db, ratio, knee_db, attack_ms, release_ms,
            makeup_gain_db, start_sample, end_sample
        )

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reverb', methods=['POST'])
def reverb():
    """
    Apply convolution reverb using manual convolution.

    Feature-parity addition: matches AudioMass's Reverb effect (which
    convolves the signal with a synthetic decaying-noise impulse via a
    ConvolverNode). Here the impulse is built and convolved manually
    (see dsp.reverb.apply_reverb), reusing the same discrete_convolution
    used by the Echo effect above.
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        duration_s = float(data.get('durationS', 1.5))
        decay = float(data.get('decay', 2.0))
        mix = float(data.get('mix', 0.3))
        reverse = bool(data.get('reverse', False))
        seed = data.get('seed', None)
        seed = int(seed) if seed is not None else None
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        # Estimate cost before running: same formula as
        # create_reverb_impulse() in dsp/reverb.py. Use the REGION length
        # (what will actually be convolved), not the whole clip.
        impulse_length = int(track.editor.sample_rate * duration_s)
        region_start, region_end = track.editor._resolve_region(start_sample, end_sample)
        signal_length = region_end - region_start
        est_seconds = estimate_convolution_seconds(signal_length, impulse_length)

        if est_seconds > CONVOLUTION_TIME_LIMIT_SEC:
            return jsonify({
                'error': (
                    f'This would take about {est_seconds:.0f} seconds to process '
                    f'(selection is {signal_length / track.editor.sample_rate:.1f}s long). '
                    f'Try a smaller room size or a shorter selection.'
                ),
                'estimatedSeconds': round(est_seconds, 1)
            }), 400

        track.editor.reverb(duration_s, decay, mix, reverse, seed, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/normalize', methods=['POST'])
def normalize():
    """
    Normalize to a target peak or RMS level (manual gain solve).

    Feature-parity addition: matches AudioMass's Normalize effect.
    See dsp.basic_ops.normalize_audio.
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        target_db = float(data.get('targetDb', -1.0))
        mode = data.get('mode', 'peak')
        if mode not in ('peak', 'rms'):
            mode = 'peak'
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        track.editor.normalize(target_db, mode, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/invert', methods=['POST'])
def invert():
    """
    Flip polarity: y[n] = -x[n] (manual sign flip).

    Feature-parity addition: matches AudioMass's Invert effect.
    See dsp.basic_ops.invert_audio.
    """
    data = request.json if request.is_json else {}
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        track.editor.invert(start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/distort', methods=['POST'])
def distort():
    """
    Apply waveshaping distortion (manual soft/hard clip curves).

    Feature-parity addition: matches AudioMass's Distortion effect.
    See dsp.dynamics.apply_distortion.
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        drive_db = float(data.get('driveDb', 12.0))
        mode = data.get('mode', 'soft')
        if mode not in ('soft', 'hard'):
            mode = 'soft'
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        track.editor.distort(drive_db, mode, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/delay', methods=['POST'])
def delay():
    """
    Apply a single-tap delay line (manual sample-index recursion).

    Feature-parity addition: matches AudioMass's Delay effect.
    Distinct from Echo above: this recurses directly on the sample
    array (an IIR-style feedback loop) rather than building an
    impulse response and convolving. See dsp.dynamics.apply_delay.
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        delay_ms = float(data.get('delayMs', 300.0))
        feedback = float(data.get('feedback', 0.0))
        mix = float(data.get('mix', 0.5))
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        track.editor.delay(delay_ms, feedback, mix, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/limit', methods=['POST'])
def limit():
    """
    Apply brickwall limiting (manual peak-envelope-follower gain).

    Feature-parity addition: matches AudioMass's Hard Limiter effect.
    See dsp.dynamics.apply_hard_limiter.
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        ceiling_db = float(data.get('ceilingDb', -0.3))
        release_ms = float(data.get('releaseMs', 50.0))
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        track.editor.limit(ceiling_db, release_ms, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/speed', methods=['POST'])
def speed():
    """
    Change speed/pitch together via linear-interpolation resampling.

    Feature-parity addition: matches AudioMass's Speed Up/Slow Down
    (pitch) effect. Alters clip duration -- returns the new duration
    so the frontend can refresh its waveform/selection state.
    See dsp.speed_silence.change_speed.
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        speed_factor = float(data.get('speedFactor', 1.0))

        track.editor.change_speed(speed_factor)

        waveform = prepare_waveform(track.editor.current)
        duration_s = len(track.editor.current) / track.editor.sample_rate
        return jsonify({
            'success': True,
            'waveform': waveform,
            'durationS': duration_s,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/remove_silence', methods=['POST'])
def remove_silence_route():
    """
    Shorten long silent gaps (manual frame-energy thresholding).

    Feature-parity addition: matches AudioMass's Remove Silence
    effect. Alters clip duration -- returns the new duration so the
    frontend can refresh its waveform/selection state.
    See dsp.speed_silence.remove_silence.
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        threshold_db = float(data.get('thresholdDb', -40.0))
        min_silence_ms = float(data.get('minSilenceMs', 300.0))
        padding_ms = float(data.get('paddingMs', 50.0))

        track.editor.remove_silence(threshold_db, min_silence_ms, padding_ms)

        waveform = prepare_waveform(track.editor.current)
        duration_s = len(track.editor.current) / track.editor.sample_rate
        return jsonify({
            'success': True,
            'waveform': waveform,
            'durationS': duration_s,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reduce_noise', methods=['POST'])
def reduce_noise_route():
    """
    Apply STFT-based spectral-subtraction denoising.

    Feature-parity addition: matches AudioMass's Noise Reduction
    (Voice) effect. Manual Hann-windowed STFT, magnitude subtraction
    against an estimated noise floor, phase-preserving reconstruction
    via overlap-add ISTFT. np.fft is used as a computational
    primitive (like +/-) -- no scipy.signal or third-party denoising
    library is called. See dsp.noise_reduction.reduce_noise for the full
    derivation.
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        noise_sample_s = float(data.get('noiseSampleS', 0.5))
        reduction_db = float(data.get('reductionDb', 12.0))
        frame_size = int(data.get('frameSize', 2048))

        track.editor.reduce_noise(noise_sample_s, reduction_db, frame_size)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/repair/declick', methods=['POST'])
def declick_route():
    """
    Audio Repair -> Click Reduction.

    Detects short transient clicks (vinyl pops, mouth clicks) via an
    adaptive derivative-spike detector and smooths over them with a
    cubic Hermite spline. See dsp.repair.declick_channel for the full
    derivation (ported from AudioMass's deClickChannel).
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        sensitivity = data.get('sensitivity', 'medium')
        if sensitivity not in ('low', 'medium', 'high'):
            sensitivity = 'medium'
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        fixed_count = track.editor.declick(sensitivity, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'fixedCount': fixed_count,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/repair/edit', methods=['POST'])
def repair_edit_route():
    """
    Audio Repair -> Edit Repair.

    Detects abrupt edit-point discontinuities (a hard splice between two
    takes with a DC-offset/level mismatch) and smooths over them with a
    cubic Hermite spline. See dsp.repair.repair_splice_channel for the
    full derivation (ported from AudioMass's repairSpliceChannel).
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        sensitivity = data.get('sensitivity', 'medium')
        if sensitivity not in ('low', 'medium', 'high'):
            sensitivity = 'medium'
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        fixed_count = track.editor.repair_edit(sensitivity, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'fixedCount': fixed_count,
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/repair/hum', methods=['POST'])
def hum_reduce_route():
    """
    Audio Repair -> Hum Reduction.

    Auto-detects (via the Goertzel algorithm) or accepts a forced 50/60Hz
    mains hum frequency, then notches it and its harmonics out with a
    chain of biquad notch filters. See dsp.hum_removal.resolve_hum_freq /
    dsp.hum_removal.hum_notch for the full derivation (ported from AudioMass's
    resolveHumFreq / HumNotch).
    """
    data = request.json
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        mode = data.get('mode', 'auto')  # 'auto' | '50' | '60'
        harmonics = int(data.get('harmonics', 8))
        q = float(data.get('q', 12.0))
        start_sample, end_sample = resolve_selection_samples(data, track.editor.sample_rate)

        # Same cost guard rationale as the multiband EQ guard above:
        # hum_notch() chains `harmonics` sequential notch biquads (via
        # multiband_eq's cascade) over each channel of the selected
        # region. Uses the same measured per-band-second constant.
        region_start, region_end = track.editor._resolve_region(start_sample, end_sample)
        region_seconds = (region_end - region_start) / track.editor.sample_rate
        num_channels = 1 if track.editor.current.ndim == 1 else track.editor.current.shape[1]
        est_seconds = region_seconds * harmonics * num_channels * MULTIBAND_EQ_SEC_PER_BAND_SECOND
        if est_seconds > BIQUAD_CASCADE_TIME_LIMIT_SEC:
            return jsonify({
                'error': (
                    f'This would take about {est_seconds:.0f} seconds to process '
                    f'(selection is {region_seconds:.1f}s long with {harmonics} harmonics). '
                    f'Try fewer harmonics or a shorter selection.'
                ),
                'estimatedSeconds': round(est_seconds, 1)
            }), 400

        detected_freq = track.editor.hum_reduce(mode, harmonics, q, start_sample, end_sample)

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'detectedFreq': round(detected_freq, 2),
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/undo', methods=['POST'])
def undo():
    """Undo the last operation on ONE specific track (per-track undo history)."""
    data = request.json if request.is_json else {}
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        # track.editor.undo() returns the label of what it just undid
        # (e.g. "Apply Fade Out (fx)"), or None if undo_stack was empty
        # and nothing happened. Check stack emptiness explicitly rather
        # than the return value's truthiness -- an unlabeled frame
        # legitimately returns None on a SUCCESSFUL undo too, and
        # `if not result` would misreport that as "nothing to undo".
        had_something_to_undo = len(track.editor.undo_stack) > 0
        undone_label = track.editor.undo()

        if had_something_to_undo:
            waveform = prepare_waveform(track.editor.current)
            return jsonify({
                'success': True,
                'waveform': waveform,
                'duration': len(track.editor.current) / track.editor.sample_rate,
                'samples': len(track.editor.current),
                'undoneLabel': undone_label,
                'undoLabel': track.editor.undo_label,
                'redoLabel': track.editor.redo_label
            })
        else:
            return jsonify({'success': False, 'message': 'Nothing to undo'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/redo', methods=['POST'])
def redo():
    """Redo the last undone operation on ONE specific track."""
    data = request.json if request.is_json else {}
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        had_something_to_redo = len(track.editor.redo_stack) > 0
        redone_label = track.editor.redo()

        if had_something_to_redo:
            waveform = prepare_waveform(track.editor.current)
            return jsonify({
                'success': True,
                'waveform': waveform,
                'duration': len(track.editor.current) / track.editor.sample_rate,
                'samples': len(track.editor.current),
                'redoneLabel': redone_label,
                'undoLabel': track.editor.undo_label,
                'redoLabel': track.editor.redo_label
            })
        else:
            return jsonify({'success': False, 'message': 'Nothing to redo'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reset', methods=['POST'])
def reset():
    """Reset ONE track to its own original audio (before/after comparison)."""
    data = request.json if request.is_json else {}
    track, err = get_track_or_error(data.get('trackId'))
    if err:
        return err

    try:
        track.editor.reset_to_original()

        waveform = prepare_waveform(track.editor.current)
        return jsonify({
            'success': True,
            'waveform': waveform,
            'duration': len(track.editor.current) / track.editor.sample_rate,
            'samples': len(track.editor.current),
            'undoLabel': track.editor.undo_label,
            'redoLabel': track.editor.redo_label
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/get_original', methods=['GET'])
def get_original():
    """
    Get the original (pre-edit) audio as base64-encoded WAV, for the
    "Compare with Original" waveform in the browser.

    Mirrors get_audio_data() below, but encodes track.editor.original
    instead of track.editor.current -- the frontend's
    wavesurferOriginal.load(data.audioData) needs a decodable audio
    source here, not the plain sample array prepare_waveform() returns.
    """
    # GET request -- trackId comes from the query string, not a JSON
    # body (see get_track_or_error()'s docstring on why the two GET vs
    # POST conventions differ here).
    track, err = get_track_or_error(request.args.get('trackId'))
    if err:
        return err

    try:
        buffer = io.BytesIO()
        sf.write(buffer, track.editor.original, track.editor.sample_rate, format='WAV')
        buffer.seek(0)

        audio_base64 = base64.b64encode(buffer.read()).decode('utf-8')

        return jsonify({
            'success': True,
            'audioData': f'data:audio/wav;base64,{audio_base64}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export', methods=['GET'])
def export():
    """Export ONE track's own current audio as a WAV file."""
    track, err = get_track_or_error(request.args.get('trackId'))
    if err:
        return err

    try:
        buffer = io.BytesIO()
        sf.write(buffer, track.editor.current, track.editor.sample_rate, format='WAV')
        buffer.seek(0)

        download_name = f"{track.name or 'track'}.wav"
        return send_file(
            buffer,
            mimetype='audio/wav',
            as_attachment=True,
            download_name=download_name
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export_mix', methods=['GET'])
def export_mix():
    """
    Export the full multi-track MIXDOWN (every non-muted track, summed
    at its own timeline position) as one stereo WAV file -- the
    multi-track counterpart to /api/export above, which only ever
    exports a single track's own audio. See
    MultiTrackSession.mix_down() / mix_tracks_to_stereo() in
    dsp/mixing.py for the actual mixing DSP.
    """
    if session is None or not session.tracks:
        return jsonify({'error': 'No audio loaded'}), 400

    try:
        mixed = session.mix_down()

        buffer = io.BytesIO()
        sf.write(buffer, mixed, session.sample_rate, format='WAV')
        buffer.seek(0)

        return send_file(
            buffer,
            mimetype='audio/wav',
            as_attachment=True,
            download_name='mixdown.wav'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/get_audio_data', methods=['GET'])
def get_audio_data():
    """
    Get one track's current audio data as base64-encoded WAV for
    playback in browser.
    """
    track, err = get_track_or_error(request.args.get('trackId'))
    if err:
        return err

    try:
        buffer = io.BytesIO()
        sf.write(buffer, track.editor.current, track.editor.sample_rate, format='WAV')
        buffer.seek(0)

        # Encode as base64 for embedding in HTML5 audio element
        audio_base64 = base64.b64encode(buffer.read()).decode('utf-8')

        return jsonify({
            'success': True,
            'audioData': f'data:audio/wav;base64,{audio_base64}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# TRACK MANAGEMENT (multi-track session)
# ============================================================================
# Creating a track happens via /api/upload above (every upload adds a
# track to the session -- there's no separate "create empty track"
# route, since a track without audio isn't yet meaningful to anything
# else in this file). These three routes cover the rest of a track's
# lifecycle: listing what exists, removing one, and repositioning one
# on the shared timeline.

@app.route('/api/tracks', methods=['GET'])
def list_tracks():
    """
    List every track currently in the session, in creation order, as
    lightweight summaries (see Track.to_summary_dict() in dsp/track.py)
    -- names, colors, positions, mute state, NOT full audio/waveform
    data. The frontend fetches each track's own waveform separately
    (via get_audio_data/upload's own response) only for tracks it's
    actually about to render, rather than this one route eagerly
    returning everything for every track regardless of whether it's
    currently visible.
    """
    if session is None:
        return jsonify({'success': True, 'tracks': [], 'sampleRate': None})

    return jsonify({
        'success': True,
        'tracks': session.list_tracks(),
        'sampleRate': session.sample_rate
    })


@app.route('/api/tracks/<track_id>', methods=['DELETE'])
def remove_track(track_id):
    """
    Remove one track from the session entirely (its own undo history,
    audio, and timeline position all go with it -- there is no undo
    for removing a track itself, matching how removing a track is
    treated as a structural session edit rather than a content edit;
    see Track's own class docstring in dsp/track.py for the same
    distinction drawn between content edits and position edits).
    """
    if session is None:
        return jsonify({'error': 'No audio loaded'}), 400

    removed = session.remove_track(track_id)
    if not removed:
        return jsonify({'error': f'No track with id {track_id}'}), 404

    return jsonify({'success': True, 'removedTrackId': track_id})


@app.route('/api/tracks/<track_id>/move', methods=['POST'])
def move_track(track_id):
    """
    Reposition a track's clip on the shared timeline (see
    Track.move_to() in dsp/track.py). Deliberately NOT one of the
    per-track effect routes above -- moving a clip isn't a content
    edit, so it doesn't go through track.editor at all, and undoing a
    move (via /api/tracks/<id>/undo_move below) is entirely separate
    from track.editor's own undo/redo stack.

    Body: {'startSeconds': float} -- the new position, in seconds, on
    the shared timeline (converted to samples here at the session's
    shared sample rate, same seconds-in/samples-stored convention every
    other route in this file already uses).
    """
    track, err = get_track_or_error(track_id)
    if err:
        return err

    try:
        data = request.json
        start_seconds = float(data.get('startSeconds', 0.0))
        start_sample = int(round(start_seconds * track.editor.sample_rate))

        track.move_to(start_sample)

        return jsonify({'success': True, 'track': track.to_summary_dict()})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tracks/<track_id>/undo_move', methods=['POST'])
def undo_move_track(track_id):
    """
    Undo the last move_track() call for this track, if there was one.
    Separate from /api/undo above by design -- see move_track()'s own
    docstring.
    """
    track, err = get_track_or_error(track_id)
    if err:
        return err

    restored = track.undo_move()
    return jsonify({
        'success': True,
        'restored': restored,
        'track': track.to_summary_dict()
    })


@app.route('/api/tracks/<track_id>/mute', methods=['POST'])
def set_track_muted(track_id):
    """
    Set a track's muted flag. Body: {'muted': bool}. A muted track is
    excluded from mix_down() entirely (see MultiTrackSession.mix_down()
    docstring in dsp/track.py) but keeps playing normally in its own
    per-track preview -- muting only affects the combined mix, not
    that track's own solo playback/editing.
    """
    track, err = get_track_or_error(track_id)
    if err:
        return err

    try:
        data = request.json
        track.muted = bool(data.get('muted', False))
        return jsonify({'success': True, 'track': track.to_summary_dict()})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/session', methods=['DELETE'])
def clear_session():
    """
    Drop the ENTIRE session -- every track, all their undo/redo history,
    everything -- and return to a blank slate. The single explicit
    "start over" action the multi-track model needs (see MultiTrackSession
    in dsp/track.py): once /api/upload always ADDS a track rather than
    replacing the session, there has to be some way back to zero tracks
    that isn't "remove them one at a time".
    """
    global session
    session = None
    return jsonify({'success': True})


def prepare_waveform(audio: np.ndarray, max_points: int = 5000) -> list:
    """
    Downsample waveform data for efficient visualization.

    For large audio files, send only a subset of samples to the frontend.

    Args:
        audio: Audio array (mono or stereo)
        max_points: Maximum number of points to return

    Returns:
        List of sample values (mono) or list of [L, R] pairs (stereo)
    """
    if audio.ndim == 1:
        # Mono
        if len(audio) <= max_points:
            return audio.tolist()
        else:
            # Downsample by taking every Nth sample
            step = len(audio) // max_points
            return audio[::step].tolist()
    else:
        # Stereo: return left channel for waveform display
        # (can be extended to show both channels)
        left_channel = audio[:, 0]
        if len(left_channel) <= max_points:
            return left_channel.tolist()
        else:
            step = len(left_channel) // max_points
            return left_channel[::step].tolist()


def match_channels(audio_to_match: np.ndarray, reference_audio: np.ndarray) -> np.ndarray:
    """
    Convert audio to have the same number of channels as reference.

    Args:
        audio_to_match: Audio to convert
        reference_audio: Reference audio (determines target channel count)

    Returns:
        Converted audio with matching channel count
    """
    target_channels = 1 if reference_audio.ndim == 1 else reference_audio.shape[1]
    source_channels = 1 if audio_to_match.ndim == 1 else audio_to_match.shape[1]

    if source_channels == target_channels:
        return audio_to_match

    if target_channels == 1 and source_channels == 2:
        # Stereo to mono: average both channels
        return np.mean(audio_to_match, axis=1)

    if target_channels == 2 and source_channels == 1:
        # Mono to stereo: duplicate channel
        return np.column_stack([audio_to_match, audio_to_match])

    return audio_to_match


if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)

    print("\n" + "="*70)
    print("  Mini Audio Editor - CSE220 Signals & Linear Systems Project")
    print("="*70)
    print("\n  Server starting at http://localhost:5000")
    print("  Open this URL in your web browser to use the editor.\n")
    print("="*70 + "\n")

    app.run(debug=True, port=5000)
