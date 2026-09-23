// ============================================================================
// Mini Audio Editor - Frontend JavaScript
// CSE220 Signals & Linear Systems Project
//
// Handles UI interactions (menu bar, effect dock, transport), WaveSurfer.js
// waveform display, and API communication.
//
// MULTI-TRACK MODEL: the backend now holds a MultiTrackSession (see
// audio_dsp.py/app.py) of N tracks (N >= 0) instead of one global
// editor_instance. This file mirrors that client-side: `tracks` is a
// registry keyed by trackId, each entry holding everything ONE track
// needs (its own WaveSurfer instances, its own current drag-selection,
// its own decoded AudioBuffer for shared playback) -- there is no
// longer a single implicit "the" track. `selectedTrackId` is the new
// single point of global state: whichever track's lane the user last
// clicked, and the ONLY thing the Effects/Edit menus, undo/redo, and
// the selection readout ever act on. A single-track session is simply
// N=1 with that one track always selected -- there is no separate
// single-track code path.
// ============================================================================

const TRACK_WAVE_HEIGHT = 90;       // must match .track-waveform's CSS height
// The original lane is deliberately the SAME height as the edited one:
// two signals drawn on one amplitude axis are only comparable if a
// given amplitude is also the same number of pixels in both lanes.
const TRACK_ORIGINAL_HEIGHT = TRACK_WAVE_HEIGHT;  // must match .track-original-lane's CSS height

let tracks = {};            // trackId -> track state object, see makeTrackState()
let selectedTrackId = null; // whichever track's lane is highlighted / menu-targeted
let sessionSampleRate = null;

// SIGNAL-COMPARISON DISPLAY MODE (see setAmplitudeScale()).
// true  -> every lane is drawn against the SAME absolute amplitude axis
//          (-1.0 .. +1.0 full scale), so "the edited signal is now half
//          the amplitude of the original" is visible at a glance.
// false -> WaveSurfer's own per-lane peak normalization (each lane's own
//          loudest sample is stretched to full height), which looks nicer
//          for very quiet clips but makes two lanes incomparable.
// Absolute is the default precisely because this is a signals project:
// the point of the display is comparing an operation's OUTPUT against its
// INPUT, and per-lane normalization hides exactly that difference.
let absoluteAmplitudeScale = true;

// Shared playback engine (one AudioContext driving every track's
// AudioBuffer in sync, rather than N independent <audio>/WaveSurfer
// elements trying to stay sample-locked to each other -- see
// initSharedPlayback()'s own comment block for the full reasoning).
let sharedAudioContext = null;
let sharedPlaybackSources = [];  // active AudioBufferSourceNodes, cleared on stop
let sharedPlaybackStartedAt = 0; // AudioContext.currentTime when play began
let sharedPlaybackOffset = 0;    // seconds into the timeline playback started at
let isPlaying = false;
let playheadAnimationFrame = null;

function makeTrackState(summary) {
    // One entry in `tracks`, seeded from a backend Track.to_summary_dict()
    // response (trackId/name/color/muted/startSample/durationSeconds) plus
    // the client-only fields every track needs: its own WaveSurfer
    // instances (created lazily once its lane is actually rendered), its
    // own drag-selection region, and its own decoded AudioBuffer (for
    // shared playback -- fetched/decoded lazily on first play, not on
    // every track add, since decoding is not free).
    return {
        id: summary.trackId,
        name: summary.name,
        color: summary.color,
        muted: summary.muted,
        startSample: summary.startSample,
        startSeconds: summary.startSeconds,
        durationSeconds: summary.durationSeconds,
        wavesurfer: null,
        wavesurferOriginal: null,
        comparisonMode: true,   // the original lane now sits permanently under
                                 // the edited one (View > Show Original Lane can
                                 // still hide it), instead of being an opt-in
                                 // "compare" mode -- a processed signal is only
                                 // meaningful next to the signal it came from.
        currentRegion: null,
        waveform: null,       // downsampled peaks, from upload/apply responses
        audioBuffer: null,    // decoded Web Audio buffer, for shared playback
        originalAudioBuffer: null,   // decoded ORIGINAL (pre-edit) audio, so the
                                      // original lane is playable from the marker
                                      // exactly like the edited lane
        originalDurationSeconds: null,
        playbackSource: 'edited',    // 'edited' | 'original' -- which of the two
                                      // lanes this track actually plays when the
                                      // transport runs
        lastUndoLabel: null,  // cached from the last mutating call's response --
        lastRedoLabel: null,  // see refreshMenusForSelectedTrack()'s own comment
        includedInPlayback: true,  // separate from both `selected` (which track
                                    // Effects/Edit target) and `muted` (excluded
                                    // from mixdown/export too) -- this is purely
                                    // "does this track play the next time Play is
                                    // pressed". To play one track alone: check it,
                                    // uncheck the rest. Defaults to true so a
                                    // freshly added track plays along with
                                    // whatever's already there, matching how
                                    // adding a track already means "join the mix"
                                    // rather than starting silent.
    };
}

function getSelectedTrack() {
    return selectedTrackId ? tracks[selectedTrackId] : null;
}

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    initializeMenuBar();
    initializeEffectDock();
    initializeFileInputs();
    initializeTransport();
    initializeSliderUpdates();
    initializeEditMenuActions();
});

// ============================================================================
// Menu Bar (File / Edit / Effects / View / Help dropdowns)
// ============================================================================

function initializeMenuBar() {
    const menuItems = document.querySelectorAll('.menu-item');

    menuItems.forEach((item) => {
        const trigger = item.querySelector('.menu-trigger');
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            const wasOpen = item.classList.contains('menu-open');
            closeAllMenus();
            if (!wasOpen) {
                item.classList.add('menu-open');
            }
        });
    });

    // Effects menu: each option opens a panel in the effect dock
    document.querySelectorAll('.menu-dropdown [data-panel]').forEach((btn) => {
        btn.addEventListener('click', () => {
            if (btn.disabled) return;
            openEffectPanel(btn.dataset.panel, btn.textContent.trim());
            closeAllMenus();
        });
    });

    document.addEventListener('click', closeAllMenus);

    // File menu
    document.getElementById('menuLoadAudio').addEventListener('click', () => {
        document.getElementById('audioFile').click();
    });
    document.getElementById('menuJoinAudio').addEventListener('click', () => {
        document.getElementById('joinFile').click();
    });
    document.getElementById('menuNewSession').addEventListener('click', startNewSession);
    document.getElementById('menuExport').addEventListener('click', exportSelectedTrack);
    document.getElementById('menuExportMix').addEventListener('click', exportMix);

    // View menu
    document.getElementById('menuToggleCompare').addEventListener('click', toggleComparison);
    document.getElementById('menuAmplitudeScale').addEventListener('click', () => {
        setAmplitudeScale(!absoluteAmplitudeScale);
    });

    // Help menu
    document.getElementById('menuAbout').addEventListener('click', () => {
        showToast('CSE220 project — every effect below is manually implemented DSP (no np.convolve / scipy.signal shortcuts). See README for the math.', 'info');
    });
}

function closeAllMenus() {
    document.querySelectorAll('.menu-item.menu-open').forEach((item) => {
        item.classList.remove('menu-open');
    });
}

function initializeEditMenuActions() {
    document.getElementById('menuUndo').addEventListener('click', undo);
    document.getElementById('menuRedo').addEventListener('click', redo);
    document.getElementById('menuTrim').addEventListener('click', trimAudio);
    document.getElementById('menuReverseAll').addEventListener('click', () => reverseAudio(false));
    document.getElementById('menuReverseSelection').addEventListener('click', () => reverseAudio(true));
    document.getElementById('menuReset').addEventListener('click', resetToOriginal);
}

// ============================================================================
// Effect Modal (centered overlay opened from the Effects menu)
// ============================================================================

function initializeEffectDock() {
    document.getElementById('effectDockClose').addEventListener('click', closeEffectDock);

    // Click the dimmed backdrop (but not the modal card itself) to close,
    // same as clicking outside any standard modal dialog.
    document.getElementById('effectModalBackdrop').addEventListener('click', (e) => {
        if (e.target.id === 'effectModalBackdrop') {
            closeEffectDock();
        }
    });

    // Escape closes the open effect modal. Checked against the backdrop's
    // own display style (not a separate isOpen flag) so this can never
    // drift out of sync with what's actually on screen.
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && document.getElementById('effectModalBackdrop').style.display !== 'none') {
            closeEffectDock();
        }
    });
}

function openEffectPanel(panelId, title) {
    const panel = document.getElementById(panelId);
    if (!panel) return;

    const dockBody = document.getElementById('effectDockBody');
    dockBody.innerHTML = '';
    dockBody.appendChild(panel);
    panel.style.display = 'flex';

    document.getElementById('effectDockTitle').textContent = title;
    document.getElementById('effectModalBackdrop').style.display = 'flex';
}

function closeEffectDock() {
    document.getElementById('effectModalBackdrop').style.display = 'none';
    // Return the panel to its inert template container so a future
    // openEffectPanel() call can find it there again if needed, and
    // it doesn't linger detached in the dock body.
    const dockBody = document.getElementById('effectDockBody');
    const templateHolder = document.getElementById('effectPanels');
    Array.from(dockBody.children).forEach((child) => {
        templateHolder.appendChild(child);
    });
}

function setEffectsMenuEnabled(enabled) {
    document.querySelectorAll('.menu-dropdown [data-panel]').forEach((btn) => {
        btn.disabled = !enabled;
    });
    document.getElementById('menuExport').disabled = !enabled;
    document.getElementById('menuJoinAudio').disabled = !enabled;
    // menuUndo/menuRedo are NOT set here -- their disabled state and
    // label text are driven entirely by updateUndoRedoLabels(), called
    // after every upload/apply/undo/redo/reset response. Right after a
    // fresh upload both stacks are empty, so forcing them enabled here
    // would let the user click Undo only to see "Nothing to undo".
    document.getElementById('menuTrim').disabled = !enabled;
    document.getElementById('menuReverseAll').disabled = !enabled;
    document.getElementById('menuReverseSelection').disabled = !enabled;
    document.getElementById('menuReset').disabled = !enabled;
    document.getElementById('menuToggleCompare').disabled = !enabled;
    document.getElementById('playBtn').disabled = !enabled;
    document.getElementById('stopBtn').disabled = !enabled;
    document.getElementById('clearSelectionBtn').disabled = !enabled;
    // menuNewSession/menuExportMix are SESSION-level (any tracks exist
    // at all), not selected-TRACK-level -- driven separately by
    // renderTrackList()/startNewSession() rather than here, since a
    // session with tracks but nothing currently selected should still
    // allow "New Session" and "Export Mixdown".
}

// Refreshes the Edit menu's Undo/Redo items to show the specific
// action each would affect, e.g. "Undo Apply Fade Out (fx)" -- mirrors
// AudioMass's own Edit menu, which names the actual operation next to
// Undo/Redo instead of leaving them as bare, generic labels.
// undoLabel/redoLabel come straight from the backend's undo_label /
// redo_label properties (always freshly read off the real stack tops),
// echoed back in the JSON of every upload/apply/undo/redo/reset call --
// so this only ever reflects genuine stack state, never a guess based
// on "whichever button the user clicked last".
function updateUndoRedoLabels(undoLabel, redoLabel) {
    const undoBtn = document.getElementById('menuUndo');
    const redoBtn = document.getElementById('menuRedo');
    const undoLabelSpan = document.getElementById('menuUndoLabel');
    const redoLabelSpan = document.getElementById('menuRedoLabel');

    if (undoLabel) {
        undoLabelSpan.innerHTML = `Undo <em>${escapeHtml(undoLabel)}</em>`;
        undoBtn.disabled = false;
    } else {
        undoLabelSpan.textContent = 'Undo';
        undoBtn.disabled = true;
    }

    if (redoLabel) {
        redoLabelSpan.innerHTML = `Redo <em>${escapeHtml(redoLabel)}</em>`;
        redoBtn.disabled = false;
    } else {
        redoLabelSpan.textContent = 'Redo';
        redoBtn.disabled = true;
    }
}

// Undo/redo labels are always plain hardcoded strings from app.py
// (e.g. "Apply Fade Out (fx)"), never raw user input -- but this is
// assigned via innerHTML for the <em> wrapper, so escape defensively
// rather than assuming the server-side whitelist can never change.
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ============================================================================
// File Inputs
// ============================================================================

function initializeFileInputs() {
    document.getElementById('loadAudioBtn').addEventListener('click', () => {
        document.getElementById('audioFile').click();
    });
    document.getElementById('addTrackBtn').addEventListener('click', () => {
        document.getElementById('audioFile').click();
    });
    document.getElementById('audioFile').addEventListener('change', handleFileUpload);
    document.getElementById('joinFile').addEventListener('change', handleJoinFile);
}

// ============================================================================
// Transport Bar
// ============================================================================

function initializeTransport() {
    document.getElementById('playBtn').addEventListener('click', togglePlayback);
    document.getElementById('stopBtn').addEventListener('click', stopPlayback);
    document.getElementById('clearSelectionBtn').addEventListener('click', clearRegions);
}

// ============================================================================
// Slider live-value labels
// ============================================================================

function initializeSliderUpdates() {
    const bindings = [
        ['gainSlider', 'gainValue'],
        ['fadeDuration', 'fadeDurationValue'],
        ['normTarget', 'normTargetValue'],
        ['eqLowGain', 'eqLowGainValue'],
        ['eqMidGain', 'eqMidGainValue'],
        ['eqHighGain', 'eqHighGainValue'],
        ['compThreshold', 'compThresholdValue'],
        ['compRatio', 'compRatioValue'],
        ['compAttack', 'compAttackValue'],
        ['compRelease', 'compReleaseValue'],
        ['limitCeiling', 'limitCeilingValue'],
        ['limitRelease', 'limitReleaseValue'],
        ['echoDelay', 'echoDelayValue'],
        ['echoDecay', 'echoDecayValue'],
        ['echoCount', 'echoCountValue'],
        ['delayTime', 'delayTimeValue'],
        ['delayFeedback', 'delayFeedbackValue'],
        ['delayMix', 'delayMixValue'],
        ['reverbDuration', 'reverbDurationValue'],
        ['reverbDecay', 'reverbDecayValue'],
        ['reverbMix', 'reverbMixValue'],
        ['distDrive', 'distDriveValue'],
        ['speedFactor', 'speedFactorValue'],
        ['silenceThreshold', 'silenceThresholdValue'],
        ['silenceMinGap', 'silenceMinGapValue'],
        ['silencePadding', 'silencePaddingValue'],
        ['noiseSample', 'noiseSampleValue'],
        ['noiseReduction', 'noiseReductionValue'],
    ];

    bindings.forEach(([sliderId, labelId]) => {
        const slider = document.getElementById(sliderId);
        const label = document.getElementById(labelId);
        if (!slider || !label) return;
        slider.addEventListener('input', (e) => {
            label.textContent = e.target.value;
        });
    });

    // Effect apply buttons
    document.getElementById('applyGainBtn').addEventListener('click', applyGain);
    document.getElementById('applyFadeInBtn').addEventListener('click', () => applyFade('in'));
    document.getElementById('applyFadeOutBtn').addEventListener('click', () => applyFade('out'));
    document.getElementById('applyNormalizeBtn').addEventListener('click', applyNormalize);
    document.getElementById('applyInvertBtn').addEventListener('click', applyInvert);
    document.getElementById('applyEqBtn').addEventListener('click', applyEqualize);
    document.getElementById('applyCompressorBtn').addEventListener('click', applyCompressor);
    document.getElementById('applyLimiterBtn').addEventListener('click', applyLimiter);
    document.getElementById('applyEchoBtn').addEventListener('click', applyEcho);
    document.getElementById('applyDelayBtn').addEventListener('click', applyDelay);
    document.getElementById('applyReverbBtn').addEventListener('click', applyReverb);
    document.getElementById('applyDistortionBtn').addEventListener('click', applyDistortion);
    document.getElementById('applySpeedBtn').addEventListener('click', applySpeed);
    document.getElementById('applySilenceBtn').addEventListener('click', applyRemoveSilence);
    document.getElementById('applyNoiseBtn').addEventListener('click', applyReduceNoise);

    initPresetSelects();
    initParagraphicEq();
    initGraphicEq();
    initAudioRepair();
}

// ============================================================================
// WaveSurfer Setup
// ============================================================================

// Builds a vertical CanvasGradient for WaveSurfer's waveColor/progressColor.
// WaveSurfer accepts a CanvasGradient anywhere it accepts a CSS color string,
// but the gradient has to be created against a real canvas 2D context first --
// the coordinates are in canvas pixel space, top (0) to bottom (height).
function makeWaveGradient(height, colorTop, colorBottom) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, colorTop);
    gradient.addColorStop(1, colorBottom);
    return gradient;
}

function createTrackWaveSurfer(trackId) {
    const track = tracks[trackId];
    if (!track) return;

    if (track.wavesurfer) {
        track.wavesurfer.destroy();
    }

    // TRACK_WAVE_HEIGHT must match .track-waveform's CSS height
    // (static/style.css) -- WaveSurfer's canvas always renders at
    // exactly this height regardless of its container's size, so the
    // two must agree or a dead zone reappears below the waveform where
    // drag-selection silently fails to register (see the historical
    // comment on #waveform's old CSS rule for the original bug this
    // discipline comes from).
    const container = document.querySelector(`#trackWaveform-${trackId}`);
    if (!container) return;

    track.wavesurfer = WaveSurfer.create({
        container: container,
        waveColor: makeWaveGradient(TRACK_WAVE_HEIGHT, '#f2a65e', '#8b6ef2'),
        progressColor: makeWaveGradient(TRACK_WAVE_HEIGHT, '#ffcf8c', '#b39bff'),
        cursorColor: '#ff6b6b',
        barWidth: 2,
        barGap: 1,
        barRadius: 1,
        height: TRACK_WAVE_HEIGHT,
        // normalize=false draws the bars against the true -1..+1 sample
        // range instead of rescaling each lane to its own peak, so the
        // edited lane and the original lane below it share one amplitude
        // axis and an operation's effect on level is directly visible
        // (see absoluteAmplitudeScale / setAmplitudeScale()).
        normalize: !absoluteAmplitudeScale,
        backend: 'WebAudio',
        interact: false,  // shared playback drives the timeline; clicking a
                           // lane's waveform should select the track, not
                           // seek that lane's own independent playback.
        plugins: [
            WaveSurfer.regions.create({
                dragSelection: {
                    slop: 5
                },
                color: 'rgba(139, 110, 242, 0.22)'
            })
        ]
    });

    // NOTE: no play/pause/finish/audioprocess listeners here. Each
    // track's WaveSurfer instance is a VISUAL widget only (waveform
    // bars + drag-selection) -- actual audio playback for the whole
    // session is driven by the single shared AudioContext engine (see
    // initSharedPlayback()), which schedules every track's own
    // AudioBuffer together so N tracks stay sample-locked to one
    // shared clock instead of N independent WaveSurfer players trying
    // to stay in sync with each other.

    track.wavesurfer.on('region-created', (region) => {
        const regions = Object.values(track.wavesurfer.regions.list);
        regions.forEach(r => {
            if (r.id !== region.id) {
                r.remove();
            }
        });
        track.currentRegion = region;
        if (selectedTrackId === trackId) {
            updateSelectionInfo(region);
        }
    });

    track.wavesurfer.on('region-updated', (region) => {
        track.currentRegion = region;
        if (selectedTrackId === trackId) {
            updateSelectionInfo(region);
        }
    });
}

// The per-track ORIGINAL (pre-edit) waveform, drawn in its own lane
// directly beneath the edited one. Same geometry and -- critically --
// the same amplitude scaling as createTrackWaveSurfer() above, because
// the entire point of the two stacked lanes is that their bar heights
// mean the same thing.
function createOriginalWaveSurfer(trackId) {
    const track = tracks[trackId];
    if (!track) return;

    const container = document.querySelector(`#trackOriginal-${trackId}`);
    if (!container) return;

    if (track.wavesurferOriginal) {
        track.wavesurferOriginal.destroy();
    }

    track.wavesurferOriginal = WaveSurfer.create({
        container: container,
        waveColor: makeWaveGradient(TRACK_ORIGINAL_HEIGHT, '#8a8792', '#4f4d58'),
        progressColor: makeWaveGradient(TRACK_ORIGINAL_HEIGHT, '#a3a1b0', '#6b6976'),
        cursorColor: '#ff6b6b',
        barWidth: 2,
        barGap: 1,
        barRadius: 1,
        height: TRACK_ORIGINAL_HEIGHT,
        normalize: !absoluteAmplitudeScale,
        backend: 'WebAudio',
        interact: false
    });
}

// Fetches the track's untouched original audio once and keeps it both
// drawn (original lane) and decoded (originalAudioBuffer), so "play the
// original from wherever the marker is" needs no extra round trip.
async function loadOriginalToWaveSurfer(trackId) {
    const track = tracks[trackId];
    if (!track || !track.wavesurferOriginal) return;

    try {
        const response = await fetch(`/api/get_original?trackId=${encodeURIComponent(trackId)}`);
        const data = await response.json();
        if (!data.success) return;

        await track.wavesurferOriginal.load(data.audioData);
        track.originalAudioBuffer = await decodeAudioDataUrl(data.audioData);
        track.originalDurationSeconds = track.originalAudioBuffer.duration;

        layoutTrackLanes();
        updateTrackStats(trackId);
    } catch (error) {
        console.error(`Error loading original audio for track ${trackId}:`, error);
    }
}

// A faint horizontal grid (+1.0 / +0.5 / 0 / -0.5 / -1.0) drawn over a
// waveform lane. With absolute scaling on, these lines are real
// amplitude gridlines shared by both lanes, so the two signals can be
// read against each other -- not just compared by eye.
function addAmplitudeGrid(container) {
    if (!container || container.querySelector('.amp-grid')) return;
    const grid = document.createElement('div');
    grid.className = 'amp-grid';
    ['1.0', '0.5', '0', '0.5', '1.0'].forEach((label, i) => {
        const line = document.createElement('div');
        line.className = 'amp-grid-line' + (i === 2 ? ' amp-grid-zero' : '');
        line.style.top = `${i * 25}%`;
        line.innerHTML = `<span class="amp-grid-label">${i < 2 ? '+' : (i > 2 ? '−' : '')}${label}</span>`;
        grid.appendChild(line);
    });
    container.appendChild(grid);
}

// ============================================================================
// Track List Rendering (multi-track lanes)
// ============================================================================

// Rebuilds every .track-lane in #trackList from the current `tracks`
// registry. Called after any structural change (track added/removed) --
// NOT after every small update (mute toggle, waveform refresh), which
// instead patch their own lane's DOM directly (see setTrackMuted() /
// refreshTrackWaveform() below) so a full rebuild doesn't destroy and
// recreate every OTHER track's WaveSurfer instance just because one
// track's mute state changed.
function renderTrackList() {
    const trackListEl = document.getElementById('trackList');
    const placeholderEl = document.getElementById('waveformPlaceholder');
    const addTrackBtn = document.getElementById('addTrackBtn');
    const trackIds = Object.keys(tracks);

    // Session-level menu items (any tracks exist at all, independent of
    // which one -- if any -- is currently selected). Track-level items
    // are handled separately by setEffectsMenuEnabled(), driven by
    // refreshMenusForSelectedTrack() instead.
    document.getElementById('menuNewSession').disabled = trackIds.length === 0;
    document.getElementById('menuExportMix').disabled = trackIds.length === 0;

    if (trackIds.length === 0) {
        trackListEl.style.display = 'none';
        addTrackBtn.style.display = 'none';
        placeholderEl.style.display = 'flex';
        trackListEl.innerHTML = '';
        return;
    }

    placeholderEl.style.display = 'none';
    trackListEl.style.display = 'flex';
    addTrackBtn.style.display = 'inline-flex';

    trackListEl.innerHTML = '';

    trackIds.forEach((trackId) => {
        const track = tracks[trackId];
        const lane = document.createElement('div');
        lane.className = 'track-lane' + (trackId === selectedTrackId ? ' selected' : '');
        lane.id = `trackLane-${trackId}`;
        lane.style.setProperty('--track-color', track.color);

        lane.innerHTML = `
            <div class="track-lane-header" data-track-id="${trackId}">
                <input type="checkbox" class="track-play-checkbox" data-track-id="${trackId}" ${track.includedInPlayback ? 'checked' : ''} title="Include in playback">
                <span class="track-color-dot"></span>
                <span class="track-name" title="${escapeHtml(track.name)}">${escapeHtml(track.name)}</span>
                <span class="track-lane-header-spacer"></span>
                <span class="track-source-toggle" data-track-id="${trackId}" title="Which signal this track plays from the marker">
                    <button class="track-source-btn${track.playbackSource === 'edited' ? ' active' : ''}" data-source="edited">Edited</button>
                    <button class="track-source-btn${track.playbackSource === 'original' ? ' active' : ''}" data-source="original">Original</button>
                </span>
                <span class="track-position-badge">${formatTime(track.startSeconds)} start</span>
                <button class="track-mute-btn${track.muted ? ' muted' : ''}" data-track-id="${trackId}" title="Mute (excludes from mixdown)">M</button>
                <button class="track-remove-btn" data-track-id="${trackId}" title="Remove track">✕</button>
            </div>
            <!-- SIGNAL STACK: processed output on top, the input it came
                 from immediately below it, both on the same time axis and
                 the same amplitude axis, so the operation itself is what
                 the eye picks out. Each .signal-row is the full session
                 timeline; the .wave-clip inside it is positioned/sized to
                 the portion of that timeline the audio actually occupies
                 (layoutTrackLanes()), which is what makes the marker line
                 up with the samples under it. -->
            <div class="signal-row signal-row-edited" data-track-id="${trackId}">
                <span class="signal-row-tag">Edited (y[n])</span>
                <div class="wave-clip" id="trackWaveClip-${trackId}">
                    <div class="track-waveform" id="trackWaveform-${trackId}"></div>
                </div>
            </div>
            <div class="signal-row signal-row-original" data-track-id="${trackId}" style="display: ${track.comparisonMode ? 'block' : 'none'};">
                <span class="signal-row-tag">Original (x[n])</span>
                <div class="wave-clip" id="trackOriginalClip-${trackId}">
                    <div class="track-original-lane" id="trackOriginal-${trackId}"></div>
                </div>
            </div>
            <div class="signal-stats" id="trackStats-${trackId}"></div>
            <div class="track-position-strip" id="trackPositionStrip-${trackId}"></div>
        `;

        trackListEl.appendChild(lane);

        // Selecting: clicking anywhere in the header EXCEPT the
        // mute/remove buttons themselves (handled separately below,
        // with stopPropagation so a mute click doesn't also select).
        lane.querySelector('.track-lane-header').addEventListener('click', (e) => {
            if (e.target.closest('.track-mute-btn') || e.target.closest('.track-remove-btn')
                || e.target.closest('.track-play-checkbox')) {
                return;
            }
            selectTrack(trackId);
        });

        lane.querySelector('.track-play-checkbox').addEventListener('click', (e) => {
            e.stopPropagation();
        });
        lane.querySelector('.track-play-checkbox').addEventListener('change', (e) => {
            const t = tracks[trackId];
            if (t) t.includedInPlayback = e.target.checked;
        });

        // Edited / Original playback-source switch: which of the two
        // stacked signals this track feeds to the shared transport.
        lane.querySelectorAll('.track-source-btn').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                setTrackPlaybackSource(trackId, btn.dataset.source);
            });
        });

        lane.querySelector('.track-mute-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            toggleTrackMute(trackId);
        });

        lane.querySelector('.track-remove-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            removeTrack(trackId);
        });

        // WaveSurfer instances need their container element to already
        // exist in the DOM before WaveSurfer.create() runs, so this
        // happens after appendChild() above, not before.
        createTrackWaveSurfer(trackId);
        loadAudioToWaveSurfer(trackId);
        createOriginalWaveSurfer(trackId);
        loadOriginalToWaveSurfer(trackId);

        addAmplitudeGrid(lane.querySelector(`#trackWaveClip-${trackId}`));
        addAmplitudeGrid(lane.querySelector(`#trackOriginalClip-${trackId}`));

        // Click anywhere on either signal row to move the marker there
        // (and start playing from there if the transport is running).
        lane.querySelectorAll('.signal-row').forEach((row) => wireSeekOnElement(row, trackId));

        renderTrackPositionStrip(trackId);
    });

    layoutTrackLanes();
    updateSharedPlayheadRange();
}

// ============================================================================
// Lane geometry: every lane is the SAME time axis
// ============================================================================
// Each .signal-row spans the full session timeline (0 .. session
// duration). The .wave-clip inside it is placed at the track's own
// start offset and sized to its own duration, so a sample drawn at
// x pixels is genuinely at the same instant in every lane -- which is
// what lets one shared marker be correct for all of them, and what
// makes the edited and original signals line up sample-for-sample
// when nothing changed the duration.
function layoutTrackLanes() {
    const total = getSessionDurationSeconds();
    if (total <= 0) return;

    Object.values(tracks).forEach((track) => {
        const place = (clipEl, durationSeconds, ws) => {
            if (!clipEl || !durationSeconds) return;
            const left = (track.startSeconds / total) * 100;
            const width = Math.max((durationSeconds / total) * 100, 0.5);
            const changed = clipEl.style.width !== `${width}%`;
            clipEl.style.left = `${left}%`;
            clipEl.style.width = `${width}%`;
            // WaveSurfer sizes its canvas once at load time, so a clip
            // that just changed width has to be told to redraw.
            if (changed && ws) {
                try { ws.drawBuffer(); } catch (e) { /* not loaded yet */ }
            }
        };

        place(
            document.getElementById(`trackWaveClip-${track.id}`),
            track.durationSeconds,
            track.wavesurfer
        );
        place(
            document.getElementById(`trackOriginalClip-${track.id}`),
            track.originalDurationSeconds || track.durationSeconds,
            track.wavesurferOriginal
        );
    });
}

// ============================================================================
// Marker (click-to-seek)
// ============================================================================
// Clicking anywhere on a lane, the ruler, or the clip strip moves the
// shared marker to that instant -- and, if audio is already playing,
// playback jumps there instead of continuing from the old position
// (seekSharedPlayback() restarts the scheduled sources at the new
// offset). A click is distinguished from a drag-selection / clip drag
// by a small movement threshold, so dragging out a region never also
// moves the marker.
const SEEK_CLICK_SLOP_PX = 5;

function wireSeekOnElement(element, trackId = null) {
    if (!element || element.dataset.seekWired === '1') return;
    element.dataset.seekWired = '1';

    let downX = null;
    let downY = null;

    element.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        if (e.target.closest('.track-clip-block')) return;  // that's a clip drag
        downX = e.clientX;
        downY = e.clientY;
    });

    element.addEventListener('pointerup', (e) => {
        if (downX === null) return;
        const moved = Math.hypot(e.clientX - downX, e.clientY - downY);
        downX = downY = null;
        if (moved > SEEK_CLICK_SLOP_PX) return;          // it was a drag
        if (e.target.closest('.track-clip-block')) return;

        const rect = element.getBoundingClientRect();
        if (rect.width <= 0) return;
        const fraction = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
        const total = getSessionDurationSeconds();
        if (total <= 0) return;

        if (trackId) selectTrack(trackId);
        seekSharedPlayback(fraction * total);
    });
}

// ============================================================================
// Playback source switch (edited vs original)
// ============================================================================
function setTrackPlaybackSource(trackId, source) {
    const track = tracks[trackId];
    if (!track || (source !== 'edited' && source !== 'original')) return;

    track.playbackSource = source;

    const lane = document.getElementById(`trackLane-${trackId}`);
    if (lane) {
        lane.querySelectorAll('.track-source-btn').forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.source === source);
        });
        lane.classList.toggle('playing-original', source === 'original');
    }

    // Switching mid-playback should be audible immediately, so re-arm
    // the scheduled sources from the marker's current position rather
    // than only taking effect at the next Play.
    if (isPlaying) {
        seekSharedPlayback(getCurrentPlayheadSeconds());
    }

    updateSharedPlayheadRange();
    showToast(
        source === 'original'
            ? `"${track.name}" will play its ORIGINAL (unprocessed) signal`
            : `"${track.name}" will play its EDITED signal`,
        'info'
    );
}

// ============================================================================
// Signal comparison readout (original vs edited, in numbers)
// ============================================================================
// The stacked waveforms show the shape of an operation; these figures
// pin down its size. Peak and RMS are computed over the actual decoded
// buffers, in dBFS, alongside the change each one underwent.
function measureBuffer(buffer) {
    if (!buffer) return null;
    let peak = 0;
    let sumSquares = 0;
    let count = 0;
    for (let ch = 0; ch < buffer.numberOfChannels; ch++) {
        const data = buffer.getChannelData(ch);
        for (let i = 0; i < data.length; i++) {
            const v = data[i];
            const a = v < 0 ? -v : v;
            if (a > peak) peak = a;
            sumSquares += v * v;
        }
        count += data.length;
    }
    return {
        peak,
        rms: count ? Math.sqrt(sumSquares / count) : 0,
        duration: buffer.duration
    };
}

function toDb(value) {
    if (!value || value <= 0) return '−∞';
    return (20 * Math.log10(value)).toFixed(1);
}

function formatDelta(editedValue, originalValue) {
    if (!originalValue || !editedValue) return '—';
    const delta = 20 * Math.log10(editedValue / originalValue);
    const sign = delta > 0 ? '+' : '';
    return `${sign}${delta.toFixed(1)} dB`;
}

function updateTrackStats(trackId) {
    const track = tracks[trackId];
    const el = document.getElementById(`trackStats-${trackId}`);
    if (!track || !el) return;

    const edited = measureBuffer(track.audioBuffer);
    const original = measureBuffer(track.originalAudioBuffer);
    if (!edited && !original) {
        el.innerHTML = '';
        return;
    }

    const cell = (label, value) => `<span class="signal-stat"><em>${label}</em> ${value}</span>`;

    el.innerHTML = [
        cell('x[n] peak', original ? `${toDb(original.peak)} dBFS` : '—'),
        cell('y[n] peak', edited ? `${toDb(edited.peak)} dBFS` : '—'),
        cell('Δ peak', edited && original ? formatDelta(edited.peak, original.peak) : '—'),
        cell('Δ RMS', edited && original ? formatDelta(edited.rms, original.rms) : '—'),
        cell('length', edited && original
            ? `${formatTime(original.duration)} → ${formatTime(edited.duration)}`
            : '—'),
    ].join('');
}

// ============================================================================
// Amplitude scale toggle (View menu)
// ============================================================================
function setAmplitudeScale(absolute) {
    absoluteAmplitudeScale = absolute;

    Object.values(tracks).forEach((track) => {
        [track.wavesurfer, track.wavesurferOriginal].forEach((ws) => {
            if (!ws) return;
            ws.params.normalize = !absolute;
            try { ws.drawBuffer(); } catch (e) { /* nothing loaded yet */ }
        });
    });

    document.querySelectorAll('.amp-grid').forEach((grid) => {
        grid.classList.toggle('amp-grid-relative', !absolute);
    });

    const item = document.getElementById('menuAmplitudeScale');
    if (item) {
        item.classList.toggle('menu-option-active', absolute);
        const label = document.getElementById('menuAmplitudeScaleLabel');
        if (label) {
            label.textContent = absolute
                ? 'Amplitude Scale: Absolute (−1…+1)'
                : 'Amplitude Scale: Fit each lane';
        }
    }

    showToast(
        absolute
            ? 'Absolute amplitude scale — lanes are directly comparable'
            : 'Per-lane fit — each lane is scaled to its own peak',
        'info'
    );
}

// ============================================================================
// Timeline ruler (shared time axis above every lane; click to seek)
// ============================================================================
// m:ss is too coarse for short clips -- with a sub-second tick step it
// prints the same label several times in a row, which reads as a broken
// axis. Below 1s per tick, label in seconds with one decimal instead.
function formatRulerTime(seconds, step) {
    if (step < 1) return `${seconds.toFixed(1)}s`;
    return formatTime(seconds);
}

function renderTimelineRuler() {
    const ruler = document.getElementById('timelineRuler');
    if (!ruler) return;

    const total = getSessionDurationSeconds();
    if (total <= 0) {
        ruler.innerHTML = '';
        ruler.style.display = 'none';
        return;
    }

    ruler.style.display = 'block';

    // ~10 ticks, snapped to a readable step.
    const rawStep = total / 10;
    const niceSteps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
    const step = niceSteps.find((s) => s >= rawStep) || 600;

    let html = '';
    for (let t = 0; t <= total + 1e-9; t += step) {
        const left = (t / total) * 100;
        html += `<span class="ruler-tick" style="left:${left}%"><i></i><b>${formatRulerTime(t, step)}</b></span>`;
    }
    ruler.innerHTML = html;

    wireSeekOnElement(ruler);
}
// WaveSurfer normally decodes/loads audio itself via wavesurfer.load(url),
// but every track's actual audio lives server-side keyed by trackId --
// there is no single ambient "current audio" to hand it anymore.
// loadAudioToWaveSurfer(trackId) (below, near the effect/upload handlers)
// is what actually fetches and decodes a track's real audio into both
// its WaveSurfer instance (for accurate bars) and its AudioBuffer (for
// shared playback) -- called after upload and after every effect apply.

function selectTrack(trackId) {
    if (!tracks[trackId]) return;
    if (selectedTrackId === trackId) return;

    const previousId = selectedTrackId;
    selectedTrackId = trackId;

    // Patch just the two affected lanes' classes rather than a full
    // renderTrackList() -- switching selection doesn't need to
    // destroy/recreate any WaveSurfer instance.
    if (previousId && document.getElementById(`trackLane-${previousId}`)) {
        document.getElementById(`trackLane-${previousId}`).classList.remove('selected');
    }
    const newLane = document.getElementById(`trackLane-${trackId}`);
    if (newLane) {
        newLane.classList.add('selected');
    }

    refreshMenusForSelectedTrack();
}

// Re-scopes the Effects/Edit menus, Undo/Redo labels, selection readout,
// and Compare-with-Original toggle to whichever track is now selected --
// called on selectTrack() and after any track add/remove.
function refreshMenusForSelectedTrack() {
    const track = getSelectedTrack();

    document.getElementById('selTrackName').textContent = track ? `(${track.name})` : '';

    if (track && track.currentRegion) {
        updateSelectionInfo(track.currentRegion);
    } else {
        clearSelectionInfoDisplay();
    }

    setEffectsMenuEnabled(!!track);

    if (track) {
        // Cached from whichever mutating call (upload/apply/undo/redo)
        // last touched this specific track -- selection-switching alone
        // never changes a track's own undo/redo state, so there's
        // nothing to fetch from the server here, just redisplay what's
        // already known for this track.
        updateUndoRedoLabels(track.lastUndoLabel || null, track.lastRedoLabel || null);
    } else {
        updateUndoRedoLabels(null, null);
    }

    document.getElementById('menuToggleCompare').classList.toggle(
        'menu-option-active', track ? track.comparisonMode : false
    );
}

// ============================================================================
// Shared Playback Engine
// ============================================================================
// Plays every unmuted track together against ONE AudioContext clock,
// each starting at the correct offset into ITS OWN buffer for
// wherever the shared playhead currently is on the timeline. Chosen
// over N independent WaveSurfer players (one per track) because
// keeping several separate <audio>-backed players sample-locked to
// each other during playback -- especially after a seek -- is
// genuinely fragile; scheduling N AudioBufferSourceNodes against one
// shared AudioContext.currentTime is the standard, reliable way to
// keep multiple sources in sync (this is exactly what a real
// multi-track engine does).

function getSharedAudioContext() {
    if (!sharedAudioContext) {
        sharedAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    return sharedAudioContext;
}

// The session's own timeline length, in seconds: the latest point any
// track's audio actually ends, accounting for its own start offset --
// same definition mix_tracks_to_stereo() uses server-side for the
// mixdown's own length (see audio_dsp.py), kept consistent here so the
// transport's displayed total and the actual exported mix always agree.
function getSessionDurationSeconds() {
    let maxEnd = 0;
    Object.values(tracks).forEach((t) => {
        const end = t.startSeconds + getTrackPlayDuration(t);
        if (end > maxEnd) maxEnd = end;
    });
    return maxEnd;
}

// How long this track occupies the timeline right now: the length of
// whichever signal it is currently set to play (edited or original --
// an edit like Trim or Speed makes the two differ), falling back to the
// edited length.
function getTrackPlayDuration(track) {
    if (track.playbackSource === 'original' && track.originalDurationSeconds) {
        return track.originalDurationSeconds;
    }
    return track.durationSeconds || 0;
}

// The AudioBuffer the transport should schedule for this track.
function getTrackPlaybackBuffer(track) {
    return track.playbackSource === 'original'
        ? (track.originalAudioBuffer || track.audioBuffer)
        : track.audioBuffer;
}

// Current playhead position, in seconds, whether or not playback is
// currently running -- reads live off the AudioContext clock while
// playing, otherwise returns wherever playback last stopped/sought to.
function getCurrentPlayheadSeconds() {
    if (isPlaying) {
        const ctx = getSharedAudioContext();
        return sharedPlaybackOffset + (ctx.currentTime - sharedPlaybackStartedAt);
    }
    return sharedPlaybackOffset;
}

async function startSharedPlayback() {
    const ctx = getSharedAudioContext();
    if (ctx.state === 'suspended') {
        await ctx.resume();
    }

    stopAllPlaybackSources();  // clears any leftover nodes from a previous play

    const startAt = sharedPlaybackOffset;
    const trackIds = Object.keys(tracks);

    // Ensure every track has a decoded AudioBuffer before scheduling
    // anything -- decoding is async, and starting some tracks' sources
    // while others are still decoding would desync the very first
    // playback after a fresh page load.
    await Promise.all(trackIds.map(async (id) => {
        const t = tracks[id];
        if (!t.audioBuffer) {
            await loadAudioToWaveSurfer(id);
        }
        // A track set to play its ORIGINAL signal needs that buffer
        // decoded too before anything is scheduled.
        if (t.playbackSource === 'original' && !t.originalAudioBuffer) {
            await loadOriginalToWaveSurfer(id);
        }
    }));

    const contextStartTime = ctx.currentTime + 0.05;  // tiny lead-in so every
                                                        // node's start() call
                                                        // lands before playback
                                                        // audibly begins
    sharedPlaybackStartedAt = contextStartTime;

    trackIds.forEach((id) => {
        const t = tracks[id];
        // Muted tracks never play (mute always means silent, in both
        // playback and export). includedInPlayback is a SEPARATE, purely
        // playback-time filter on top of that -- unchecking it lets the
        // person play a subset of tracks together (or just one, by
        // unchecking all the others) without touching mute/export state
        // at all.
        const buffer = getTrackPlaybackBuffer(t);
        if (t.muted || !t.includedInPlayback || !buffer) return;

        const trackEnd = t.startSeconds + buffer.duration;
        if (trackEnd <= startAt) return;  // this track has already fully
                                            // played out before the seek point

        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);

        if (t.startSeconds >= startAt) {
            // Track starts AFTER the playhead -- schedule it to begin
            // later, playing from its own sample 0.
            const delay = t.startSeconds - startAt;
            source.start(contextStartTime + delay, 0);
        } else {
            // Track already started before the playhead -- begin
            // immediately, but part-way INTO its own buffer.
            const intoBuffer = startAt - t.startSeconds;
            source.start(contextStartTime, intoBuffer);
        }

        sharedPlaybackSources.push(source);
    });

    isPlaying = true;
    updatePlayButton();
    animatePlayhead();
}

function pauseSharedPlayback() {
    if (!isPlaying) return;
    sharedPlaybackOffset = getCurrentPlayheadSeconds();
    stopAllPlaybackSources();
    isPlaying = false;
    updatePlayButton();
    cancelAnimationFrame(playheadAnimationFrame);
}

function stopSharedPlayback() {
    stopAllPlaybackSources();
    sharedPlaybackOffset = 0;
    isPlaying = false;
    updatePlayButton();
    cancelAnimationFrame(playheadAnimationFrame);
    updateSharedPlayheadPosition(0);
    updateTransportClock(0);
}

function stopAllPlaybackSources() {
    sharedPlaybackSources.forEach((src) => {
        try { src.stop(); } catch (e) { /* already stopped/ended -- fine */ }
    });
    sharedPlaybackSources = [];
}

function seekSharedPlayback(seconds) {
    const wasPlaying = isPlaying;
    if (wasPlaying) {
        stopAllPlaybackSources();
        cancelAnimationFrame(playheadAnimationFrame);
    }
    sharedPlaybackOffset = Math.max(0, seconds);
    updateSharedPlayheadPosition(sharedPlaybackOffset);
    updateTransportClock(sharedPlaybackOffset);
    if (wasPlaying) {
        startSharedPlayback();
    }
}

function animatePlayhead() {
    if (!isPlaying) return;

    const current = getCurrentPlayheadSeconds();
    const total = getSessionDurationSeconds();

    if (current >= total) {
        stopSharedPlayback();
        return;
    }

    updateSharedPlayheadPosition(current);
    updateTransportClock(current);
    playheadAnimationFrame = requestAnimationFrame(animatePlayhead);
}

// Positions .shared-playhead's `left` as a fraction of the session's
// own total duration across the full width of .track-list -- every
// lane spans the same underlying timeline, so one shared left-percentage
// lines the playhead up correctly against all of them at once.
function updateSharedPlayheadPosition(seconds) {
    const playheadEl = document.getElementById('sharedPlayhead');
    if (!playheadEl) return;

    const total = getSessionDurationSeconds();
    if (total <= 0) {
        playheadEl.style.display = 'none';
        return;
    }

    playheadEl.style.display = 'block';
    const fraction = Math.min(1, seconds / total);
    playheadEl.style.left = `${fraction * 100}%`;
}

function updateSharedPlayheadRange() {
    layoutTrackLanes();
    renderTimelineRuler();
    updateSharedPlayheadPosition(getCurrentPlayheadSeconds());
    updateTransportClock(getCurrentPlayheadSeconds());
}

function updateTransportClock(currentSeconds) {
    const total = getSessionDurationSeconds();
    const timeEl = document.getElementById('transportTime');
    const totalEl = document.getElementById('transportTotal');
    if (timeEl) timeEl.textContent = formatTime(currentSeconds);
    if (totalEl) totalEl.textContent = formatTime(total);
}

function updatePlayButton() {
    const iconEl = document.getElementById('playBtnIcon');
    if (iconEl) {
        iconEl.textContent = isPlaying ? '⏸' : '▶';
    }
}

async function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    showLoading(Object.keys(tracks).length === 0 ? 'Loading audio file...' : 'Adding track...');

    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.success) {
            const trackId = data.track.trackId;
            tracks[trackId] = makeTrackState(data.track);
            tracks[trackId].waveform = data.waveform;
            tracks[trackId].lastUndoLabel = data.undoLabel;
            tracks[trackId].lastRedoLabel = data.redoLabel;
            sessionSampleRate = data.sample_rate;

            selectedTrackId = trackId;  // newly added track is auto-selected

            const metaStrip = document.getElementById('audioMetaStrip');
            metaStrip.style.display = 'flex';
            metaStrip.innerHTML = `
                <span><b>${escapeHtml(file.name)}</b></span>
                <span>Duration: <b>${formatTime(data.duration)}</b></span>
                <span>Sample Rate: <b>${data.sample_rate} Hz</b></span>
                <span>Channels: <b>${data.channels === 1 ? 'Mono' : 'Stereo'}</b></span>
                <span>Samples: <b>${data.samples.toLocaleString()}</b></span>
            `;

            renderTrackList();
            refreshMenusForSelectedTrack();
            updateLoadAudioMenuLabel();

            showToast(
                Object.keys(tracks).length === 1
                    ? 'Audio loaded successfully!'
                    : `Added "${tracks[trackId].name}" as a new track!`,
                'success'
            );
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('[ERROR] Upload exception:', error);
        showToast('Failed to upload audio file: ' + error.message, 'error');
    } finally {
        hideLoading();
        event.target.value = '';
    }
}

// "Load Audio File" reads as an odd label once tracks already exist --
// switches to "Add Track" so the File menu's wording matches what the
// action actually does at each stage (see the button/menu-item's own
// <span id="menuLoadAudioLabel">/#addTrackBtn markup in index.html).
function updateLoadAudioMenuLabel() {
    const label = document.getElementById('menuLoadAudioLabel');
    if (label) {
        label.textContent = Object.keys(tracks).length === 0 ? 'Load Audio File' : 'Add Track';
    }
}

// ============================================================================
// Track Position (drag-to-reposition on the timeline)
// ============================================================================
// Draws each track's clip as a colored block on its own
// .track-position-strip, positioned/sized as a fraction of the WHOLE
// SESSION's duration (getSessionDurationSeconds()) so every track's
// strip lines up against the same shared timeline the playhead uses --
// not each track's own local 0..duration range, which would make two
// tracks' blocks incomparable at a glance.

function renderTrackPositionStrip(trackId) {
    const track = tracks[trackId];
    const stripEl = document.getElementById(`trackPositionStrip-${trackId}`);
    if (!track || !stripEl) return;

    stripEl.innerHTML = '';

    const total = getSessionDurationSeconds();
    if (total <= 0) return;

    const block = document.createElement('div');
    block.className = 'track-clip-block';
    block.id = `trackClipBlock-${trackId}`;
    positionClipBlock(block, track, total);
    stripEl.appendChild(block);

    wireClipBlockDrag(trackId, block, stripEl);
    // Clicking the empty part of the strip is also a marker move.
    wireSeekOnElement(stripEl, trackId);
}

function positionClipBlock(block, track, totalSeconds) {
    const leftFraction = track.startSeconds / totalSeconds;
    const widthFraction = track.durationSeconds / totalSeconds;
    block.style.left = `${leftFraction * 100}%`;
    block.style.width = `${Math.max(widthFraction * 100, 0.5)}%`;  // floor width so
                                                                     // very short clips
                                                                     // stay grabbable
}

function wireClipBlockDrag(trackId, block, stripEl) {
    let dragging = false;
    let dragStartX = 0;
    let dragStartLeftFraction = 0;

    block.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        dragging = true;
        block.classList.add('dragging');
        block.setPointerCapture(e.pointerId);
        dragStartX = e.clientX;
        const track = tracks[trackId];
        const total = getSessionDurationSeconds();
        dragStartLeftFraction = total > 0 ? track.startSeconds / total : 0;

        // Dragging a track's clip is also a natural moment to select
        // that track, matching how clicking its header does the same.
        selectTrack(trackId);
    });

    block.addEventListener('pointermove', (e) => {
        if (!dragging) return;

        const track = tracks[trackId];
        const total = getSessionDurationSeconds();
        if (total <= 0) return;

        const stripWidth = stripEl.getBoundingClientRect().width;
        const deltaX = e.clientX - dragStartX;
        const deltaFraction = deltaX / stripWidth;

        let newLeftFraction = dragStartLeftFraction + deltaFraction;
        newLeftFraction = Math.max(0, newLeftFraction);  // never drag before timeline 0

        const newStartSeconds = newLeftFraction * total;

        // Live-update the visual position during the drag without
        // waiting for the server round trip -- track.startSeconds is
        // updated optimistically here, then confirmed (or corrected,
        // on failure) by the actual API call on pointerup below.
        track.startSeconds = newStartSeconds;
        track.startSample = Math.round(newStartSeconds * (sessionSampleRate || 44100));
        positionClipBlock(block, track, getSessionDurationSeconds());
        updateSharedPlayheadRange();

        const badge = document.querySelector(`#trackLane-${trackId} .track-position-badge`);
        if (badge) badge.textContent = `${formatTime(newStartSeconds)} start`;
    });

    const finishDrag = async (e) => {
        if (!dragging) return;
        dragging = false;
        block.classList.remove('dragging');

        const track = tracks[trackId];
        try {
            const response = await fetch(`/api/tracks/${encodeURIComponent(trackId)}/move`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ startSeconds: track.startSeconds })
            });
            const data = await response.json();
            if (data.success) {
                // Server-authoritative position (rounds to whole
                // samples) replaces the optimistic client value, in
                // case of any rounding drift between the two.
                track.startSeconds = data.track.startSeconds;
                track.startSample = data.track.startSample;
                renderTrackPositionStrip(trackId);
                updateSharedPlayheadRange();
            } else {
                showToast('Failed to move track: ' + data.error, 'error');
            }
        } catch (error) {
            console.error('Move track error:', error);
            showToast('Failed to move track', 'error');
        }
    };

    block.addEventListener('pointerup', finishDrag);
    block.addEventListener('pointercancel', finishDrag);
}

async function toggleTrackMute(trackId) {
    const track = tracks[trackId];
    if (!track) return;

    const newMuted = !track.muted;

    try {
        const response = await fetch(`/api/tracks/${encodeURIComponent(trackId)}/mute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ muted: newMuted })
        });
        const data = await response.json();
        if (data.success) {
            track.muted = data.track.muted;
            const btn = document.querySelector(`#trackLane-${trackId} .track-mute-btn`);
            if (btn) btn.classList.toggle('muted', track.muted);
        } else {
            showToast('Failed to update mute: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('Mute toggle error:', error);
        showToast('Failed to update mute', 'error');
    }
}

async function removeTrack(trackId) {
    const track = tracks[trackId];
    if (!track) return;

    const confirmed = confirm(`Remove "${track.name}"? This can't be undone.`);
    if (!confirmed) return;

    try {
        const response = await fetch(`/api/tracks/${encodeURIComponent(trackId)}`, {
            method: 'DELETE'
        });
        const data = await response.json();

        if (data.success) {
            if (track.wavesurfer) track.wavesurfer.destroy();
            if (track.wavesurferOriginal) track.wavesurferOriginal.destroy();
            delete tracks[trackId];

            if (selectedTrackId === trackId) {
                // Selection follows to whichever track is now first,
                // or clears entirely if that was the last track --
                // never leaves selectedTrackId pointing at a track
                // that no longer exists.
                const remainingIds = Object.keys(tracks);
                selectedTrackId = remainingIds.length > 0 ? remainingIds[0] : null;
            }

            renderTrackList();
            refreshMenusForSelectedTrack();
            updateLoadAudioMenuLabel();
            showToast(`Removed "${track.name}"`, 'info');
        } else {
            showToast('Failed to remove track: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('Remove track error:', error);
        showToast('Failed to remove track', 'error');
    }
}

async function loadAudioToWaveSurfer(trackId) {
    const track = tracks[trackId];
    if (!track || !track.wavesurfer) return;

    try {
        const response = await fetch(`/api/get_audio_data?trackId=${encodeURIComponent(trackId)}`);
        const data = await response.json();

        if (data.success) {
            await track.wavesurfer.load(data.audioData);
            // Also decode into a raw Web Audio AudioBuffer for the shared
            // playback engine (see initSharedPlayback()) -- WaveSurfer's
            // own internal buffer isn't exposed in a form this app can
            // schedule directly against a shared AudioContext clock, so
            // this decodes the same audioData a second time, once, into
            // a form the shared engine can actually use.
            track.audioBuffer = await decodeAudioDataUrl(data.audioData);
            track.durationSeconds = track.audioBuffer.duration;
            // Both the lane geometry and the original-vs-edited readout
            // depend on the buffer that just changed.
            layoutTrackLanes();
            updateTrackStats(trackId);
        }
    } catch (error) {
        console.error(`Error loading audio for track ${trackId}:`, error);
    }
}

// Decodes a data:audio/wav;base64,... URL (the shape every audio-data
// route in this app returns) into a Web Audio AudioBuffer.
async function decodeAudioDataUrl(dataUrl) {
    const base64 = dataUrl.split(',', 2)[1];
    const binaryString = atob(base64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    const ctx = getSharedAudioContext();
    return await ctx.decodeAudioData(bytes.buffer);
}

async function handleJoinFile(event) {
    const file = event.target.files[0];
    if (!file) return;

    const track = getSelectedTrack();
    if (!track) {
        showToast('Select a track first', 'info');
        event.target.value = '';
        return;
    }

    showLoading(`Joining audio onto "${track.name}"...`);

    try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('trackId', track.id);

        const response = await fetch('/api/join', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.success) {
            track.waveform = data.waveform;
            track.durationSeconds = data.duration;
            await loadAudioToWaveSurfer(track.id);
            track.lastUndoLabel = data.undoLabel;
            track.lastRedoLabel = data.redoLabel;
            if (selectedTrackId === track.id) {
                updateUndoRedoLabels(data.undoLabel, data.redoLabel);
            }
            Object.keys(tracks).forEach((id) => renderTrackPositionStrip(id));
            updateSharedPlayheadRange();
            showToast(`Joined onto "${track.name}"!`, 'success');
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('Join error:', error);
        showToast('Failed to join audio files', 'error');
    } finally {
        hideLoading();
        event.target.value = '';
    }
}

// ============================================================================
// Playback Controls
// ============================================================================

function togglePlayback() {
    if (isPlaying) {
        pauseSharedPlayback();
    } else {
        startSharedPlayback();
    }
}

function stopPlayback() {
    stopSharedPlayback();
}

// ============================================================================
// Basic Editing Operations (Trim / Reverse)
// ============================================================================

async function trimAudio() {
    const track = getSelectedTrack();
    if (!track) {
        showToast('Select a track first', 'info');
        return;
    }
    if (!track.currentRegion) {
        showToast('Please select a region first by dragging on the waveform', 'info');
        return;
    }

    showLoading('Trimming audio...');

    try {
        const start = Math.floor(track.currentRegion.start * sessionSampleRate);
        const end = Math.floor(track.currentRegion.end * sessionSampleRate);

        const response = await fetch('/api/trim', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ trackId: track.id, start, end })
        });

        const data = await response.json();

        if (data.success) {
            track.waveform = data.waveform;
            track.durationSeconds = data.duration;
            await loadAudioToWaveSurfer(track.id);
            track.lastUndoLabel = data.undoLabel;
            track.lastRedoLabel = data.redoLabel;
            if (selectedTrackId === track.id) {
                updateUndoRedoLabels(data.undoLabel, data.redoLabel);
            }
            Object.keys(tracks).forEach((id) => renderTrackPositionStrip(id));
            updateSharedPlayheadRange();
            clearRegions();
            showToast('Audio trimmed successfully!', 'success');
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('Trim error:', error);
        showToast('Failed to trim audio', 'error');
    } finally {
        hideLoading();
    }
}

async function reverseAudio(selectionOnly) {
    const track = getSelectedTrack();
    if (!track) {
        showToast('Select a track first', 'info');
        return;
    }
    if (selectionOnly && !track.currentRegion) {
        showToast('Please select a region first', 'info');
        return;
    }

    showLoading('Reversing audio...');

    try {
        const requestBody = { trackId: track.id, selectionOnly };
        if (selectionOnly && track.currentRegion) {
            // Send the ACTUAL dragged region's bounds (in seconds, same
            // convention resolve_selection_samples() expects on every
            // other effect route) rather than relying on the backend's
            // own self.selection_start/end, which may be stale from an
            // earlier, unrelated request.
            requestBody.start = track.currentRegion.start;
            requestBody.end = track.currentRegion.end;
        }

        const response = await fetch('/api/reverse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });

        const data = await response.json();

        if (data.success) {
            track.waveform = data.waveform;
            await loadAudioToWaveSurfer(track.id);
            track.lastUndoLabel = data.undoLabel;
            track.lastRedoLabel = data.redoLabel;
            if (selectedTrackId === track.id) {
                updateUndoRedoLabels(data.undoLabel, data.redoLabel);
            }
            showToast('Audio reversed successfully!', 'success');
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('Reverse error:', error);
        showToast('Failed to reverse audio', 'error');
    } finally {
        hideLoading();
    }
}

// ============================================================================
// Shared effect-apply helper
//
// Every effect below (existing and new) follows the same shape: POST a
// JSON body to an endpoint, replace the waveform on success, reload
// WaveSurfer, toast the result. This helper collapses that duplication.
// `changesDuration: true` also refreshes audioData.duration/samples from
// the response (needed for Speed and Remove Silence, which resize the
// clip -- same as Trim already does above).
//
// It also auto-attaches the current waveform selection (in seconds) as
// {start, end} on every request, so in-place effects (Gain, EQ,
// Compressor, Reverb, Distortion, Delay, Limiter, Normalize, Invert...)
// apply only to the selected region instead of always processing the
// whole file -- matching AudioMass, which always applies FX to "the
// region" and defaults to the whole file only when nothing is selected.
// Pass `wholeFile: true` in the call to opt an effect out of this (used
// by Speed / Remove Silence / Reduce Noise, which intentionally operate
// on the whole clip).
// ============================================================================

async function applyEffect({ endpoint, body, loadingMessage, successMessage, changesDuration = false, wholeFile = false }) {
    const track = getSelectedTrack();
    if (!track) {
        showToast('Select a track first', 'info');
        return;
    }

    showLoading(loadingMessage);

    try {
        const requestBody = { ...body, trackId: track.id };
        if (!wholeFile && track.currentRegion) {
            requestBody.start = track.currentRegion.start;
            requestBody.end = track.currentRegion.end;
        }

        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });

        const data = await response.json();

        if (data.success) {
            track.waveform = data.waveform;
            if (changesDuration) {
                track.durationSeconds = data.durationS;
            }
            await loadAudioToWaveSurfer(track.id);
            if (changesDuration) {
                // Duration changes shift where every LATER track's clip
                // sits relative to the session's own total length, and
                // this track's own position strip needs to reflect its
                // new width -- re-render every strip, not just this one.
                Object.keys(tracks).forEach((id) => renderTrackPositionStrip(id));
                updateSharedPlayheadRange();
            }
            track.lastUndoLabel = data.undoLabel;
            track.lastRedoLabel = data.redoLabel;
            // Every apply route now echoes back the (possibly newly
            // labeled) undo/redo stack tops -- refresh the Edit menu's
            // "Undo <name> (fx)" / "Redo <name> (fx)" text so it never
            // has to be inferred client-side from which button was
            // clicked (which would desync after Reset, page reload, etc).
            // Only refresh the visible menu if THIS track is still the
            // selected one -- an effect finishing after the user has
            // already switched to a different track shouldn't overwrite
            // that other track's menu state.
            if (selectedTrackId === track.id) {
                updateUndoRedoLabels(data.undoLabel, data.redoLabel);
            }
            const message = typeof successMessage === 'function' ? successMessage(data) : successMessage;
            showToast(message, 'success');
            // A successful Apply commits the effect -- close the modal
            // the same way the X button does, so the user lands back on
            // their waveform immediately instead of the dialog (which
            // still fully covers/blocks the editor) lingering open with
            // nothing left to do in it. Only on success: if the apply
            // failed, leave the panel open so the user can adjust
            // parameters and retry without re-opening it from the menu.
            closeEffectDock();
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    } catch (error) {
        console.error(`${endpoint} error:`, error);
        showToast('Failed to apply effect', 'error');
    } finally {
        hideLoading();
    }
}

// ============================================================================
// Effects (existing: Gain / Fade / Echo / EQ / Compressor / Reverb)
// ============================================================================

function applyGain() {
    const gainDb = parseFloat(document.getElementById('gainSlider').value);
    applyEffect({
        endpoint: '/api/gain',
        body: { gainDb },
        loadingMessage: 'Applying gain...',
        successMessage: `Gain of ${gainDb} dB applied successfully!`
    });
}

function applyFade(type) {
    const duration = parseFloat(document.getElementById('fadeDuration').value);
    const curve = document.getElementById('fadeCurve').value;
    applyEffect({
        endpoint: '/api/fade',
        body: { type, duration, curve },
        loadingMessage: `Applying fade ${type}...`,
        successMessage: `Fade ${type} applied successfully!`
    });
}

function applyEcho() {
    const delayMs = parseFloat(document.getElementById('echoDelay').value);
    const decay = parseFloat(document.getElementById('echoDecay').value);
    const numEchoes = parseInt(document.getElementById('echoCount').value);
    applyEffect({
        endpoint: '/api/echo',
        body: { delayMs, decay, numEchoes },
        loadingMessage: 'Applying echo (convolution in progress)...',
        successMessage: 'Echo effect applied successfully!'
    });
}

function applyEqualize() {
    const lowGainDb = parseFloat(document.getElementById('eqLowGain').value);
    const midGainDb = parseFloat(document.getElementById('eqMidGain').value);
    const highGainDb = parseFloat(document.getElementById('eqHighGain').value);
    applyEffect({
        endpoint: '/api/equalize',
        body: { lowGainDb, midGainDb, highGainDb },
        loadingMessage: 'Applying EQ (biquad filtering in progress)...',
        successMessage: 'EQ applied successfully!'
    });
}

function applyCompressor() {
    const thresholdDb = parseFloat(document.getElementById('compThreshold').value);
    const ratio = parseFloat(document.getElementById('compRatio').value);
    const attackMs = parseFloat(document.getElementById('compAttack').value);
    const releaseMs = parseFloat(document.getElementById('compRelease').value);
    applyEffect({
        endpoint: '/api/compress',
        body: { thresholdDb, ratio, attackMs, releaseMs },
        loadingMessage: 'Applying compressor (envelope follower in progress)...',
        successMessage: 'Compressor applied successfully!'
    });
}

function applyReverb() {
    const durationS = parseFloat(document.getElementById('reverbDuration').value);
    const decay = parseFloat(document.getElementById('reverbDecay').value);
    const mix = parseFloat(document.getElementById('reverbMix').value);
    applyEffect({
        endpoint: '/api/reverb',
        body: { durationS, decay, mix },
        loadingMessage: 'Applying reverb (convolution in progress, may take a few seconds)...',
        successMessage: 'Reverb applied successfully!'
    });
}

// ============================================================================
// Effects (new: Normalize / Invert / Distortion / Delay / Limiter /
//               Speed / Remove Silence / Noise Reduction)
// ============================================================================

function applyNormalize() {
    const targetDb = parseFloat(document.getElementById('normTarget').value);
    const mode = document.getElementById('normMode').value;
    applyEffect({
        endpoint: '/api/normalize',
        body: { targetDb, mode },
        loadingMessage: 'Normalizing...',
        successMessage: `Normalized to ${targetDb} dB (${mode})!`
    });
}

function applyInvert() {
    applyEffect({
        endpoint: '/api/invert',
        body: {},
        loadingMessage: 'Inverting polarity...',
        successMessage: 'Polarity inverted!'
    });
}

function applyDistortion() {
    const driveDb = parseFloat(document.getElementById('distDrive').value);
    const mode = document.getElementById('distMode').value;
    applyEffect({
        endpoint: '/api/distort',
        body: { driveDb, mode },
        loadingMessage: 'Applying distortion (waveshaping in progress)...',
        successMessage: 'Distortion applied successfully!'
    });
}

function applyDelay() {
    const delayMs = parseFloat(document.getElementById('delayTime').value);
    const feedback = parseFloat(document.getElementById('delayFeedback').value);
    const mix = parseFloat(document.getElementById('delayMix').value);
    applyEffect({
        endpoint: '/api/delay',
        body: { delayMs, feedback, mix },
        loadingMessage: 'Applying delay...',
        successMessage: 'Delay applied successfully!'
    });
}

function applyLimiter() {
    const ceilingDb = parseFloat(document.getElementById('limitCeiling').value);
    const releaseMs = parseFloat(document.getElementById('limitRelease').value);
    applyEffect({
        endpoint: '/api/limit',
        body: { ceilingDb, releaseMs },
        loadingMessage: 'Applying limiter (peak envelope in progress)...',
        successMessage: 'Limiter applied successfully!'
    });
}

function applySpeed() {
    const speedFactor = parseFloat(document.getElementById('speedFactor').value);
    applyEffect({
        endpoint: '/api/speed',
        body: { speedFactor },
        loadingMessage: 'Changing speed (resampling in progress)...',
        successMessage: `Speed changed to ${speedFactor}×!`,
        changesDuration: true,
        wholeFile: true
    });
}

function applyRemoveSilence() {
    const thresholdDb = parseFloat(document.getElementById('silenceThreshold').value);
    const minSilenceMs = parseFloat(document.getElementById('silenceMinGap').value);
    const paddingMs = parseFloat(document.getElementById('silencePadding').value);
    applyEffect({
        endpoint: '/api/remove_silence',
        body: { thresholdDb, minSilenceMs, paddingMs },
        loadingMessage: 'Removing silence (frame analysis in progress)...',
        successMessage: 'Silence removed successfully!',
        changesDuration: true,
        wholeFile: true
    });
}

function applyReduceNoise() {
    const noiseSampleS = parseFloat(document.getElementById('noiseSample').value);
    const reductionDb = parseFloat(document.getElementById('noiseReduction').value);
    applyEffect({
        endpoint: '/api/reduce_noise',
        body: { noiseSampleS, reductionDb, frameSize: 2048 },
        loadingMessage: 'Reducing noise (STFT spectral subtraction in progress)...',
        successMessage: 'Noise reduction applied successfully!',
        wholeFile: true
    });
}

// ============================================================================
// Undo/Redo & Reset
// ============================================================================

async function undo() {
    const track = getSelectedTrack();
    if (!track) {
        showToast('Select a track first', 'info');
        return;
    }

    showLoading('Undoing...');

    try {
        const response = await fetch('/api/undo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ trackId: track.id })
        });
        const data = await response.json();

        if (data.success) {
            if (data.waveform) {
                track.waveform = data.waveform;
                track.durationSeconds = data.duration;
                await loadAudioToWaveSurfer(track.id);
                track.lastUndoLabel = data.undoLabel;
                track.lastRedoLabel = data.redoLabel;
                if (selectedTrackId === track.id) {
                    updateUndoRedoLabels(data.undoLabel, data.redoLabel);
                }
                Object.keys(tracks).forEach((id) => renderTrackPositionStrip(id));
                updateSharedPlayheadRange();
                const what = data.undoneLabel ? `Undid: ${data.undoneLabel}` : 'Undo successful!';
                showToast(what, 'success');
            } else {
                showToast(data.message, 'info');
            }
        }
    } catch (error) {
        console.error('Undo error:', error);
        showToast('Failed to undo', 'error');
    } finally {
        hideLoading();
    }
}

async function redo() {
    const track = getSelectedTrack();
    if (!track) {
        showToast('Select a track first', 'info');
        return;
    }

    showLoading('Redoing...');

    try {
        const response = await fetch('/api/redo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ trackId: track.id })
        });
        const data = await response.json();

        if (data.success) {
            if (data.waveform) {
                track.waveform = data.waveform;
                track.durationSeconds = data.duration;
                await loadAudioToWaveSurfer(track.id);
                track.lastUndoLabel = data.undoLabel;
                track.lastRedoLabel = data.redoLabel;
                if (selectedTrackId === track.id) {
                    updateUndoRedoLabels(data.undoLabel, data.redoLabel);
                }
                Object.keys(tracks).forEach((id) => renderTrackPositionStrip(id));
                updateSharedPlayheadRange();
                const what = data.redoneLabel ? `Redid: ${data.redoneLabel}` : 'Redo successful!';
                showToast(what, 'success');
            } else {
                showToast(data.message, 'info');
            }
        }
    } catch (error) {
        console.error('Redo error:', error);
        showToast('Failed to redo', 'error');
    } finally {
        hideLoading();
    }
}

async function resetToOriginal() {
    const track = getSelectedTrack();
    if (!track) {
        showToast('Select a track first', 'info');
        return;
    }

    if (!confirm(`Reset "${track.name}" to its original audio?`)) {
        return;
    }

    showLoading('Resetting to original...');

    try {
        const response = await fetch('/api/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ trackId: track.id })
        });
        const data = await response.json();

        if (data.success) {
            track.waveform = data.waveform;
            track.durationSeconds = data.duration;
            await loadAudioToWaveSurfer(track.id);
            track.lastUndoLabel = data.undoLabel;
            track.lastRedoLabel = data.redoLabel;
            if (selectedTrackId === track.id) {
                updateUndoRedoLabels(data.undoLabel, data.redoLabel);
            }
            Object.keys(tracks).forEach((id) => renderTrackPositionStrip(id));
            updateSharedPlayheadRange();
            showToast(`Reset "${track.name}" to original audio!`, 'success');
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('Reset error:', error);
        showToast('Failed to reset', 'error');
    } finally {
        hideLoading();
    }
}

// ============================================================================
// Before/After Comparison (per track)
// ============================================================================

async function toggleComparison() {
    const track = getSelectedTrack();
    if (!track) {
        showToast('Select a track first', 'info');
        return;
    }

    track.comparisonMode = !track.comparisonMode;
    const originalRow = document.querySelector(`#trackLane-${track.id} .signal-row-original`);
    if (!originalRow) return;

    document.getElementById('menuToggleCompare').classList.toggle('menu-option-active', track.comparisonMode);

    // The original lane is now built with the lane itself (see
    // renderTrackList) and stays loaded, so this only shows/hides it --
    // it never has to fetch or rebuild the waveform again.
    if (track.comparisonMode) {
        originalRow.style.display = 'block';
        if (!track.wavesurferOriginal) {
            createOriginalWaveSurfer(track.id);
            await loadOriginalToWaveSurfer(track.id);
        }
        layoutTrackLanes();
    } else {
        originalRow.style.display = 'none';
    }
}

// ============================================================================
// Export
// ============================================================================

async function exportSelectedTrack() {
    const track = getSelectedTrack();
    if (!track) {
        showToast('Select a track first', 'info');
        return;
    }

    showLoading(`Exporting "${track.name}"...`);

    try {
        const response = await fetch(`/api/export?trackId=${encodeURIComponent(track.id)}`);

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${track.name}.wav`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            showToast('Track exported successfully!', 'success');
        } else {
            showToast('Failed to export track', 'error');
        }
    } catch (error) {
        console.error('Export error:', error);
        showToast('Failed to export track', 'error');
    } finally {
        hideLoading();
    }
}

async function exportMix() {
    if (Object.keys(tracks).length === 0) {
        showToast('No tracks to export', 'info');
        return;
    }

    showLoading('Rendering mixdown...');

    try {
        const response = await fetch('/api/export_mix');

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'mixdown.wav';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            showToast('Mixdown exported successfully!', 'success');
        } else {
            showToast('Failed to export mixdown', 'error');
        }
    } catch (error) {
        console.error('Export mix error:', error);
        showToast('Failed to export mixdown', 'error');
    } finally {
        hideLoading();
    }
}

async function startNewSession() {
    if (Object.keys(tracks).length === 0) return;

    if (!confirm('Start a new session? This removes ALL tracks and cannot be undone.')) {
        return;
    }

    showLoading('Clearing session...');

    try {
        const response = await fetch('/api/session', { method: 'DELETE' });
        const data = await response.json();

        if (data.success) {
            stopSharedPlayback();

            Object.values(tracks).forEach((track) => {
                if (track.wavesurfer) track.wavesurfer.destroy();
                if (track.wavesurferOriginal) track.wavesurferOriginal.destroy();
            });

            tracks = {};
            selectedTrackId = null;
            sessionSampleRate = null;

            // Re-zero the transport display now that `tracks` is empty --
            // stopSharedPlayback() above already reset playback state, but
            // it ran BEFORE this clear, so its own call to
            // updateTransportClock(0) still computed the OLD session
            // duration (getSessionDurationSeconds() reads live off
            // `tracks`, which wasn't empty yet at that point).
            updateTransportClock(0);
            updateSharedPlayheadPosition(0);

            document.getElementById('audioMetaStrip').style.display = 'none';
            document.getElementById('audioMetaStrip').innerHTML = '';

            renderTrackList();
            refreshMenusForSelectedTrack();
            updateLoadAudioMenuLabel();

            showToast('New session started', 'info');
        } else {
            showToast('Failed to clear session: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('New session error:', error);
        showToast('Failed to clear session', 'error');
    } finally {
        hideLoading();
    }
}

// ============================================================================
// Utility Functions
// ============================================================================

function clearRegions() {
    const track = getSelectedTrack();
    if (track && track.wavesurfer && track.wavesurfer.regions) {
        track.wavesurfer.regions.clear();
        track.currentRegion = null;
        clearSelectionInfoDisplay();
    }
}

function updateSelectionInfo(region) {
    document.getElementById('selStart').textContent = formatTime(region.start);
    document.getElementById('selEnd').textContent = formatTime(region.end);
    document.getElementById('selDuration').textContent = formatTime(region.end - region.start);
    document.getElementById('clearSelectionBtn').disabled = false;
}

function clearSelectionInfoDisplay() {
    document.getElementById('selStart').textContent = '–';
    document.getElementById('selEnd').textContent = '–';
    document.getElementById('selDuration').textContent = '–';
    document.getElementById('clearSelectionBtn').disabled = true;
}

function formatTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

function showLoading(message = 'Processing...') {
    document.getElementById('loadingMessage').textContent = message;
    document.getElementById('loadingOverlay').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loadingOverlay').style.display = 'none';
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast show ${type}`;

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// ============================================================================
// Presets dropdowns (Gain / EQ / Compressor / Delay / Reverb / Distortion / Speed)
//
// Each preset just writes values into the panel's existing sliders (same
// as if the user had dragged them by hand) and updates the live-value
// label next to each slider. Apply still works exactly as before -- the
// preset only sets values, it doesn't apply anything by itself, matching
// the AudioMass dialogs these are based on (Presets dropdown -> sliders
// update -> user still clicks Apply).
// ============================================================================

// Most sliders label themselves with an id of "<sliderId>Value", but a
// few predate that convention (the Gain panel's readout is #gainValue,
// not #gainSliderValue). Presets used to derive the label id purely
// from the slider id, so picking a Gain preset moved the slider while
// its dB readout stayed on the old number -- this map is the exception
// list that keeps preset and readout in step.
const SLIDER_LABEL_IDS = {
    gainSlider: 'gainValue',
};

function labelIdForSlider(sliderId) {
    return SLIDER_LABEL_IDS[sliderId] || `${sliderId}Value`;
}

function setSliderValue(sliderId, labelId, value) {
    const slider = document.getElementById(sliderId);
    if (!slider) return;
    slider.value = value;
    const label = document.getElementById(labelId || labelIdForSlider(sliderId));
    if (label) label.textContent = slider.value;
    // Let anything else bound to this slider (live previews, the EQ
    // curve drawing, etc.) react exactly as it would to a hand drag.
    slider.dispatchEvent(new Event('input', { bubbles: true }));
}

const GAIN_PRESETS = {
    silence: { gainSlider: -20 },
    '-12': { gainSlider: -12 },
    '-6': { gainSlider: -6 },
    '-3': { gainSlider: -3 },
    '3': { gainSlider: 3 },
    '6': { gainSlider: 6 },
    '12': { gainSlider: 12 },
};

const EQ_PRESETS = {
    flat: { eqLowGain: 0, eqMidGain: 0, eqHighGain: 0 },
    bass_boost: { eqLowGain: 8, eqMidGain: 0, eqHighGain: -2 },
    treble_boost: { eqLowGain: -2, eqMidGain: 0, eqHighGain: 8 },
    vocal_clarity: { eqLowGain: -3, eqMidGain: 5, eqHighGain: 3 },
    podcast: { eqLowGain: -4, eqMidGain: 3, eqHighGain: 2 },
    warm: { eqLowGain: 4, eqMidGain: 1, eqHighGain: -3 },
    bright: { eqLowGain: -2, eqMidGain: 1, eqHighGain: 6 },
    v_shape: { eqLowGain: 6, eqMidGain: -4, eqHighGain: 6 },
    telephone: { eqLowGain: -12, eqMidGain: 6, eqHighGain: -12 },
};

const COMP_PRESETS = {
    vocal_lead: { compThreshold: -18, compRatio: 3, compAttack: 8, compRelease: 150 },
    vocal_broadcast: { compThreshold: -20, compRatio: 6, compAttack: 3, compRelease: 100 },
    drum_bus_glue: { compThreshold: -24, compRatio: 4, compAttack: 15, compRelease: 200 },
    snare_punch: { compThreshold: -15, compRatio: 5, compAttack: 1, compRelease: 80 },
    master_gentle: { compThreshold: -12, compRatio: 2, compAttack: 20, compRelease: 300 },
    limiter_style: { compThreshold: -6, compRatio: 10, compAttack: 1, compRelease: 50 },
};

const DELAY_PRESETS = {
    slap: { delayTime: 80, delayFeedback: 0.05, delayMix: 0.3 },
    quarter_note: { delayTime: 500, delayFeedback: 0.3, delayMix: 0.4 },
    eighth_note: { delayTime: 250, delayFeedback: 0.3, delayMix: 0.4 },
    ping_pong_short: { delayTime: 150, delayFeedback: 0.4, delayMix: 0.5 },
    long_wash: { delayTime: 600, delayFeedback: 0.6, delayMix: 0.5 },
};

const REVERB_PRESETS = {
    small_room: { reverbDuration: 0.4, reverbDecay: 3.0, reverbMix: 0.2 },
    medium_room: { reverbDuration: 0.9, reverbDecay: 2.2, reverbMix: 0.3 },
    large_hall: { reverbDuration: 2.2, reverbDecay: 1.4, reverbMix: 0.4 },
    cathedral: { reverbDuration: 4.0, reverbDecay: 0.9, reverbMix: 0.5 },
    plate: { reverbDuration: 1.2, reverbDecay: 2.5, reverbMix: 0.35 },
    vocal_booth: { reverbDuration: 0.2, reverbDecay: 4.0, reverbMix: 0.12 },
    ambient_wash: { reverbDuration: 3.5, reverbDecay: 1.0, reverbMix: 0.6 },
    tight_slap: { reverbDuration: 0.15, reverbDecay: 5.0, reverbMix: 0.25 },
};

const DIST_PRESETS = {
    subtle_warmth: { distDrive: 4, distMode: 'soft' },
    crunch: { distDrive: 14, distMode: 'soft' },
    fuzz: { distDrive: 24, distMode: 'hard' },
    broken_speaker: { distDrive: 36, distMode: 'hard' },
};

const SPEED_PRESETS = {
    '0.5': { speedFactor: 0.5 },
    '0.75': { speedFactor: 0.75 },
    '0.9': { speedFactor: 0.9 },
    '1.1': { speedFactor: 1.1 },
    '1.25': { speedFactor: 1.25 },
    '2.0': { speedFactor: 2.0 },
};

function applyPresetValues(values) {
    Object.entries(values).forEach(([fieldId, val]) => {
        const el = document.getElementById(fieldId);
        if (!el) return;
        if (el.tagName === 'SELECT') {
            el.value = val;
            el.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
            setSliderValue(fieldId, labelIdForSlider(fieldId), val);
        }
    });
}

function bindPresetSelect(selectId, presetMap) {
    const select = document.getElementById(selectId);
    if (!select) return;
    select.addEventListener('change', (e) => {
        const preset = presetMap[e.target.value];
        if (preset) applyPresetValues(preset);
        // Reset back to the placeholder so picking the SAME preset twice
        // in a row still fires a change event.
        select.value = '';
    });
}

function initPresetSelects() {
    bindPresetSelect('gainPresets', GAIN_PRESETS);
    bindPresetSelect('eqPresets', EQ_PRESETS);
    bindPresetSelect('compPresets', COMP_PRESETS);
    bindPresetSelect('delayPresets', DELAY_PRESETS);
    bindPresetSelect('reverbPresets', REVERB_PRESETS);
    bindPresetSelect('distPresets', DIST_PRESETS);
    bindPresetSelect('speedPresets', SPEED_PRESETS);
}

// ============================================================================
// Paragraphic EQ
//
// A small chain of user-placed biquad bands (highpass / lowpass /
// peaking), each shown as a draggable node directly on the frequency-
// response curve -- matching AudioMass's Paragraphic EQ dialog. Dragging
// a node horizontally changes its frequency (log-scaled, 20Hz-20kHz),
// dragging vertically changes its gain (+/-24dB, clamped to 0 for
// highpass/lowpass since gain doesn't apply to them). The red curve is
// the combined response of all active bands, drawn the same way the
// biquad math actually filters (see audio_dsp.biquad_coefficients).
// ============================================================================

const PGEQ_FREQ_MIN = 20;
const PGEQ_FREQ_MAX = 20000;
const PGEQ_GAIN_RANGE = 24; // +/- dB shown on the graph
const PGEQ_COLORS = ['#e0c95c', '#5ce0d8', '#5c7de0', '#e05ca0', '#8ce05c', '#e08a5c'];

let pgeqBands = [];
let pgeqNextId = 1;
let pgeqDragId = null;
let pgeqSvgEl = null;

function pgeqDefaultBands() {
    return [
        { id: pgeqNextId++, type: 'highpass', freq: 100, gain: 0, q: 0.8, on: true },
        { id: pgeqNextId++, type: 'peaking', freq: 1000, gain: 0, q: 1.0, on: true },
        { id: pgeqNextId++, type: 'lowpass', freq: 8000, gain: 0, q: 0.8, on: true },
    ];
}

// --- log-frequency <-> x pixel, gain <-> y pixel (graph is 560x220 viewBox) ---
function pgeqFreqToX(freq) {
    const t = (Math.log10(freq) - Math.log10(PGEQ_FREQ_MIN)) / (Math.log10(PGEQ_FREQ_MAX) - Math.log10(PGEQ_FREQ_MIN));
    return 20 + t * 520;
}
function pgeqXToFreq(x) {
    const t = Math.min(1, Math.max(0, (x - 20) / 520));
    return Math.round(Math.pow(10, Math.log10(PGEQ_FREQ_MIN) + t * (Math.log10(PGEQ_FREQ_MAX) - Math.log10(PGEQ_FREQ_MIN))));
}
function pgeqGainToY(gain) {
    const t = (gain + PGEQ_GAIN_RANGE) / (2 * PGEQ_GAIN_RANGE);
    return 200 - t * 180;
}
function pgeqYToGain(y) {
    const t = Math.min(1, Math.max(0, (200 - y) / 180));
    return Math.round((t * 2 * PGEQ_GAIN_RANGE - PGEQ_GAIN_RANGE) * 10) / 10;
}

// Single-band magnitude response in dB at a given frequency, evaluated
// from the same biquad coefficient formulas as the backend (RBJ
// cookbook) so the drawn curve matches what Apply actually does.
function pgeqBandResponseDb(band, freq, sampleRate) {
    const A = Math.pow(10, band.gain / 40);
    const w0 = 2 * Math.PI * Math.min(Math.max(band.freq, 1), sampleRate / 2 - 1) / sampleRate;
    const w = 2 * Math.PI * Math.min(Math.max(freq, 1), sampleRate / 2 - 1) / sampleRate;
    const q = Math.max(band.q, 1e-4);
    const alpha = Math.sin(w0) / (2 * q);
    const cosw0 = Math.cos(w0);
    let b0, b1, b2, a0, a1, a2;

    if (band.type === 'peaking') {
        b0 = 1 + alpha * A; b1 = -2 * cosw0; b2 = 1 - alpha * A;
        a0 = 1 + alpha / A; a1 = -2 * cosw0; a2 = 1 - alpha / A;
    } else if (band.type === 'highpass') {
        b0 = (1 + cosw0) / 2; b1 = -(1 + cosw0); b2 = (1 + cosw0) / 2;
        a0 = 1 + alpha; a1 = -2 * cosw0; a2 = 1 - alpha;
    } else if (band.type === 'lowpass') {
        b0 = (1 - cosw0) / 2; b1 = 1 - cosw0; b2 = (1 - cosw0) / 2;
        a0 = 1 + alpha; a1 = -2 * cosw0; a2 = 1 - alpha;
    } else {
        return 0;
    }

    // Evaluate |H(e^jw)| via the transfer function at this frequency.
    const cosw = Math.cos(w), sinw = Math.sin(w);
    const cos2w = Math.cos(2 * w), sin2w = Math.sin(2 * w);
    const numRe = b0 + b1 * cosw + b2 * cos2w;
    const numIm = -(b1 * sinw + b2 * sin2w);
    const denRe = a0 + a1 * cosw + a2 * cos2w;
    const denIm = -(a1 * sinw + a2 * sin2w);
    const numMag = Math.sqrt(numRe * numRe + numIm * numIm);
    const denMag = Math.sqrt(denRe * denRe + denIm * denIm);
    if (denMag < 1e-12) return 0;
    return 20 * Math.log10(numMag / denMag);
}

function pgeqCombinedResponseDb(freq) {
    const sr = sessionSampleRate || 44100;
    let total = 0;
    pgeqBands.forEach((b) => {
        if (!b.on) return;
        total += pgeqBandResponseDb(b, freq, sr);
    });
    return total;
}

function pgeqRenderGraph() {
    if (!pgeqSvgEl) return;
    const ns = 'http://www.w3.org/2000/svg';
    pgeqSvgEl.innerHTML = '';

    // Gridlines (dB)
    [-24, -18, -12, -6, 0, 6, 12, 18, 24].forEach((db) => {
        const y = pgeqGainToY(db);
        const line = document.createElementNS(ns, 'line');
        line.setAttribute('x1', 20); line.setAttribute('x2', 540);
        line.setAttribute('y1', y); line.setAttribute('y2', y);
        line.setAttribute('class', db === 0 ? 'pgeq-zeroline' : 'pgeq-gridline');
        pgeqSvgEl.appendChild(line);
    });

    // Frequency labels
    [100, 1000, 10000].forEach((f) => {
        const x = pgeqFreqToX(f);
        const label = document.createElementNS(ns, 'text');
        label.setAttribute('x', x); label.setAttribute('y', 214);
        label.setAttribute('class', 'pgeq-axis-label');
        label.textContent = f >= 1000 ? `${f / 1000}k` : `${f}`;
        pgeqSvgEl.appendChild(label);
    });

    // Combined response curve
    const points = [];
    for (let px = 20; px <= 540; px += 4) {
        const freq = pgeqXToFreq(px);
        const db = Math.max(-PGEQ_GAIN_RANGE, Math.min(PGEQ_GAIN_RANGE, pgeqCombinedResponseDb(freq)));
        points.push(`${px},${pgeqGainToY(db)}`);
    }
    const curve = document.createElementNS(ns, 'polyline');
    curve.setAttribute('points', points.join(' '));
    curve.setAttribute('class', 'pgeq-curve');
    pgeqSvgEl.appendChild(curve);

    // Draggable nodes
    pgeqBands.forEach((band, idx) => {
        const cx = pgeqFreqToX(band.freq);
        const cy = pgeqGainToY(band.type === 'peaking' ? band.gain : 0);
        const circle = document.createElementNS(ns, 'circle');
        circle.setAttribute('cx', cx);
        circle.setAttribute('cy', cy);
        circle.setAttribute('r', 7);
        circle.setAttribute('fill', PGEQ_COLORS[idx % PGEQ_COLORS.length]);
        circle.setAttribute('class', 'pgeq-node' + (band.on ? '' : ' pgeq-node-off'));
        circle.dataset.bandId = band.id;
        circle.addEventListener('pointerdown', (e) => {
            pgeqDragId = band.id;
            e.target.setPointerCapture(e.pointerId);
        });
        pgeqSvgEl.appendChild(circle);
    });
}

function pgeqRenderRows() {
    const container = document.getElementById('pgeqBandRows');
    if (!container) return;
    container.innerHTML = '';

    pgeqBands.forEach((band, idx) => {
        const row = document.createElement('div');
        row.className = 'pgeq-band-row';

        const isShelfless = band.type === 'highpass' || band.type === 'lowpass';

        row.innerHTML = `
            <span class="pgeq-band-index" style="color:${PGEQ_COLORS[idx % PGEQ_COLORS.length]}">${idx + 1}</span>
            <label style="display:flex;align-items:center;gap:0.3rem;">
                <input type="checkbox" class="pgeq-band-toggle" ${band.on ? 'checked' : ''}>
            </label>
            <select class="pgeq-type-select">
                <option value="highpass" ${band.type === 'highpass' ? 'selected' : ''}>highpass</option>
                <option value="lowpass" ${band.type === 'lowpass' ? 'selected' : ''}>lowpass</option>
                <option value="peaking" ${band.type === 'peaking' ? 'selected' : ''}>peaking</option>
            </select>
            <span class="pgeq-q-field">Q <input type="number" class="pgeq-q-input" min="0.1" max="20" step="0.1" value="${band.q}"></span>
            <button class="pgeq-band-delete" title="Delete band">✕</button>
        `;

        row.querySelector('.pgeq-band-toggle').addEventListener('change', (e) => {
            band.on = e.target.checked;
            pgeqRenderGraph();
        });
        row.querySelector('.pgeq-type-select').addEventListener('change', (e) => {
            band.type = e.target.value;
            if (isShelfless) band.gain = 0;
            pgeqRenderRows();
            pgeqRenderGraph();
        });
        row.querySelector('.pgeq-q-input').addEventListener('input', (e) => {
            band.q = parseFloat(e.target.value) || 1.0;
            pgeqRenderGraph();
        });
        row.querySelector('.pgeq-band-delete').addEventListener('click', () => {
            pgeqBands = pgeqBands.filter((b) => b.id !== band.id);
            pgeqRenderRows();
            pgeqRenderGraph();
        });

        container.appendChild(row);
    });
}

function pgeqSetBands(bandDefs) {
    pgeqBands = bandDefs.map((b) => ({ id: pgeqNextId++, on: true, ...b }));
    pgeqRenderRows();
    pgeqRenderGraph();
}

const PGEQ_PRESETS = {
    flat: () => pgeqDefaultBands().map(({ id, ...b }) => b),
    old_telephone: () => [
        { type: 'highpass', freq: 400, gain: 0, q: 0.8 },
        { type: 'lowpass', freq: 3500, gain: 0, q: 0.8 },
        { type: 'peaking', freq: 1500, gain: 4, q: 1.0 },
    ],
    am_radio: () => [
        { type: 'highpass', freq: 300, gain: 0, q: 0.8 },
        { type: 'lowpass', freq: 4500, gain: 0, q: 0.8 },
        { type: 'peaking', freq: 1800, gain: 3, q: 1.2 },
    ],
    megaphone: () => [
        { type: 'highpass', freq: 500, gain: 0, q: 1.2 },
        { type: 'lowpass', freq: 3000, gain: 0, q: 1.2 },
        { type: 'peaking', freq: 1200, gain: 8, q: 2.0 },
    ],
    underwater: () => [
        { type: 'lowpass', freq: 500, gain: 0, q: 1.5 },
        { type: 'peaking', freq: 200, gain: 4, q: 1.0 },
    ],
    lofi_vintage: () => [
        { type: 'highpass', freq: 120, gain: 0, q: 0.7 },
        { type: 'lowpass', freq: 6000, gain: 0, q: 0.7 },
        { type: 'peaking', freq: 2500, gain: -3, q: 1.0 },
    ],
    bass_boost: () => [
        { type: 'highpass', freq: 30, gain: 0, q: 0.7 },
        { type: 'peaking', freq: 90, gain: 7, q: 1.2 },
        { type: 'peaking', freq: 8000, gain: -1, q: 1.0 },
    ],
    vocal_presence: () => [
        { type: 'highpass', freq: 90, gain: 0, q: 0.8 },
        { type: 'peaking', freq: 3000, gain: 4, q: 1.3 },
        { type: 'peaking', freq: 200, gain: -2, q: 1.0 },
    ],
};

function initParagraphicEq() {
    pgeqSvgEl = document.getElementById('pgeqGraph');
    if (!pgeqSvgEl) return;

    pgeqSetBands(pgeqDefaultBands().map(({ id, ...b }) => b));

    pgeqSvgEl.addEventListener('pointermove', (e) => {
        if (pgeqDragId === null) return;
        const band = pgeqBands.find((b) => b.id === pgeqDragId);
        if (!band) return;
        const rect = pgeqSvgEl.getBoundingClientRect();
        const scaleX = 560 / rect.width;
        const scaleY = 220 / rect.height;
        const x = (e.clientX - rect.left) * scaleX;
        const y = (e.clientY - rect.top) * scaleY;
        band.freq = Math.min(PGEQ_FREQ_MAX, Math.max(PGEQ_FREQ_MIN, pgeqXToFreq(x)));
        if (band.type === 'peaking') {
            band.gain = Math.min(PGEQ_GAIN_RANGE, Math.max(-PGEQ_GAIN_RANGE, pgeqYToGain(y)));
        }
        pgeqRenderRows();
        pgeqRenderGraph();
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach((evt) => {
        pgeqSvgEl.addEventListener(evt, () => { pgeqDragId = null; });
    });

    document.getElementById('pgeqAddBandBtn').addEventListener('click', () => {
        if (pgeqBands.length >= 12) {
            showToast('Maximum 12 bands', 'info');
            return;
        }
        pgeqBands.push({ id: pgeqNextId++, type: 'peaking', freq: 1000, gain: 3, q: 1.0, on: true });
        pgeqRenderRows();
        pgeqRenderGraph();
    });

    document.getElementById('pgeqPresets').addEventListener('change', (e) => {
        const fn = PGEQ_PRESETS[e.target.value];
        if (fn) pgeqSetBands(fn());
        e.target.value = '';
    });

    document.getElementById('applyPgeqBtn').addEventListener('click', applyParagraphicEq);
}

function applyParagraphicEq() {
    const bands = pgeqBands.map((b) => ({
        type: b.type, freq: b.freq, gain: b.gain, q: b.q, on: b.on
    }));
    applyEffect({
        endpoint: '/api/multiband_eq',
        // 'panel' tells the shared /api/multiband_eq route which of the
        // three EQ panels called it, purely so it can report the right
        // Undo-menu label -- see EQ_PANEL_LABELS in app.py.
        body: { bands, panel: 'paragraphic-eq' },
        loadingMessage: 'Applying Paragraphic EQ (biquad chain in progress)...',
        successMessage: 'Paragraphic EQ applied successfully!'
    });
}

// ============================================================================
// Graphic EQ (10-band and 20-band)
//
// A fixed ladder of faders, one per band: lowshelf on the first band,
// highshelf on the last, peaking for everything in between (matches
// AudioMass's GraphicEQ, which builds the exact same shelf+peaking
// biquad chain from fader values -- see audio_dsp.multiband_eq).
// ============================================================================

const GEQ10_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
const GEQ20_FREQS = [31, 44, 63, 88, 125, 180, 250, 335, 500, 710, 1000, 1400, 2000, 2800, 4000, 5600, 8000, 11300, 16000, 22000];
const GEQ10_Q = 4.6;
const GEQ20_Q = 10.2;

function geqFreqLabel(f) {
    return f >= 1000 ? `${f / 1000}k` : `${f}`;
}

function geqBuildFaders(containerId, freqs) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';

    freqs.forEach((freq, idx) => {
        const wrap = document.createElement('div');
        wrap.className = 'geq-fader';
        wrap.innerHTML = `
            <span class="geq-fader-value" data-role="value">0 db</span>
            <input type="range" min="-15" max="15" step="0.5" value="0" data-freq="${freq}" data-idx="${idx}">
            <span class="geq-fader-label">${geqFreqLabel(freq)}</span>
        `;
        const slider = wrap.querySelector('input[type="range"]');
        const valueLabel = wrap.querySelector('[data-role="value"]');
        slider.addEventListener('input', () => {
            valueLabel.textContent = `${slider.value} db`;
        });
        container.appendChild(wrap);
    });
}

function geqReadFaders(containerId, freqs, q) {
    const container = document.getElementById(containerId);
    const sliders = Array.from(container.querySelectorAll('input[type="range"]'));
    return sliders.map((slider, idx) => {
        const gain = parseFloat(slider.value) || 0;
        let type = 'peaking';
        if (idx === 0) type = 'lowshelf';
        else if (idx === sliders.length - 1) type = 'highshelf';
        return { type, freq: freqs[idx], gain, q, on: true };
    });
}

function geqSetFaders(containerId, gains) {
    const container = document.getElementById(containerId);
    const sliders = Array.from(container.querySelectorAll('input[type="range"]'));
    sliders.forEach((slider, idx) => {
        const g = gains[idx] !== undefined ? gains[idx] : 0;
        slider.value = g;
        const label = slider.parentElement.querySelector('[data-role="value"]');
        if (label) label.textContent = `${g} db`;
    });
}

// Preset gain curves, matching AudioMass's Graphic EQ presets. Indexed
// by band position (0 = lowest freq .. N-1 = highest), interpolated
// separately for the 10-band and 20-band ladders below.
function geqPresetCurve(name, numBands) {
    const shapes = {
        reset: () => new Array(numBands).fill(0),
        bass_boost: (n) => Array.from({ length: n }, (_, i) => Math.max(0, 8 - i * (8 / (n * 0.5)))),
        treble_boost: (n) => Array.from({ length: n }, (_, i) => Math.max(0, (i - n * 0.5) * (8 / (n * 0.5)))),
        vocal_clarity: (n) => Array.from({ length: n }, (_, i) => {
            const mid = n / 2;
            const dist = Math.abs(i - mid) / mid;
            return Math.max(-3, 5 * (1 - dist) - 1);
        }),
        podcast: (n) => Array.from({ length: n }, (_, i) => {
            if (i < n * 0.2) return -3;
            if (i < n * 0.6) return 3;
            if (i < n * 0.8) return 1;
            return -2;
        }),
        warm: (n) => Array.from({ length: n }, (_, i) => (i < n * 0.4 ? 3 : (i > n * 0.75 ? -3 : 0))),
        bright: (n) => Array.from({ length: n }, (_, i) => (i > n * 0.6 ? 5 : (i < n * 0.2 ? -1 : 0))),
        v_shape: (n) => Array.from({ length: n }, (_, i) => {
            const mid = (n - 1) / 2;
            return Math.round(((Math.abs(i - mid) / mid) * 7) * 10) / 10;
        }),
        loudness: (n) => Array.from({ length: n }, (_, i) => {
            const mid = (n - 1) / 2;
            const edge = Math.abs(i - mid) / mid;
            return Math.round((edge * 6) * 10) / 10;
        }),
    };
    const fn = shapes[name];
    return fn ? fn(numBands).map((v) => Math.round(v * 2) / 2) : new Array(numBands).fill(0);
}

function initGraphicEq() {
    geqBuildFaders('geq10Faders', GEQ10_FREQS);
    geqBuildFaders('geq20Faders', GEQ20_FREQS);

    document.getElementById('applyGeq10Btn').addEventListener('click', () => {
        const bands = geqReadFaders('geq10Faders', GEQ10_FREQS, GEQ10_Q);
        applyEffect({
            endpoint: '/api/multiband_eq',
            body: { bands, panel: 'graphic-eq' },
            loadingMessage: 'Applying Graphic EQ (10-band biquad chain in progress)...',
            successMessage: 'Graphic EQ applied successfully!'
        });
    });

    document.getElementById('applyGeq20Btn').addEventListener('click', () => {
        const bands = geqReadFaders('geq20Faders', GEQ20_FREQS, GEQ20_Q);
        applyEffect({
            endpoint: '/api/multiband_eq',
            body: { bands, panel: 'graphic-eq-20' },
            loadingMessage: 'Applying Graphic EQ (20-band biquad chain in progress)...',
            successMessage: 'Graphic EQ (20 bands) applied successfully!'
        });
    });

    document.getElementById('geq10Presets').addEventListener('change', (e) => {
        geqSetFaders('geq10Faders', geqPresetCurve(e.target.value, GEQ10_FREQS.length));
        e.target.value = '';
    });
    document.getElementById('geq20Presets').addEventListener('change', (e) => {
        geqSetFaders('geq20Faders', geqPresetCurve(e.target.value, GEQ20_FREQS.length));
        e.target.value = '';
    });
}

// ============================================================================
// Audio Repair (Click Reduction / Hum Reduction / Edit Repair)
// ============================================================================

const REPAIR_MODE_DESCRIPTIONS = {
    declick: 'Removes short transient clicks (vinyl pops, mouth clicks) by detecting energy spikes and interpolating across them.',
    hum: 'Detects and removes mains electrical hum (50/60Hz) and its harmonics using narrow notch filters.',
    edit: 'Detects abrupt edit-point discontinuities (a hard splice between two takes with mismatched level) and smooths over them.',
};

const REPAIR_ENDPOINTS = {
    declick: '/api/repair/declick',
    hum: '/api/repair/hum',
    edit: '/api/repair/edit',
};

function initAudioRepair() {
    const modeInputs = document.querySelectorAll('input[name="repairMode"]');
    const humRow = document.getElementById('repairHumRow');
    const sensitivityRow = document.getElementById('repairSensitivityRow');
    const desc = document.getElementById('repairModeDesc');

    function syncModeUI() {
        const mode = document.querySelector('input[name="repairMode"]:checked').value;
        desc.textContent = REPAIR_MODE_DESCRIPTIONS[mode];
        humRow.style.display = mode === 'hum' ? 'flex' : 'none';
        sensitivityRow.style.display = mode === 'hum' ? 'none' : 'flex';
    }

    modeInputs.forEach((input) => input.addEventListener('change', syncModeUI));
    syncModeUI();

    document.getElementById('applyRepairBtn').addEventListener('click', () => {
        const mode = document.querySelector('input[name="repairMode"]:checked').value;
        const endpoint = REPAIR_ENDPOINTS[mode];

        if (mode === 'hum') {
            const humMode = document.querySelector('input[name="repairHumMode"]:checked').value;
            applyEffect({
                endpoint,
                body: { mode: humMode, harmonics: 8, q: 12 },
                loadingMessage: 'Detecting and notching hum...',
                successMessage: (data) => `Hum reduction applied (${data.detectedFreq} Hz)!`
            });
            return;
        }

        const sensitivity = document.querySelector('input[name="repairSensitivity"]:checked').value;
        const loadingMessage = mode === 'declick'
            ? 'Scanning for clicks...'
            : 'Scanning for edit-point splices...';

        applyEffect({
            endpoint,
            body: { sensitivity },
            loadingMessage,
            successMessage: (data) => {
                const noun = mode === 'declick' ? 'click' : 'splice';
                const n = data.fixedCount || 0;
                if (n === 0) return `No ${noun}s found in the selection.`;
                return `Fixed ${n} ${noun}${n === 1 ? '' : 's'}!`;
            }
        });
    });
}
