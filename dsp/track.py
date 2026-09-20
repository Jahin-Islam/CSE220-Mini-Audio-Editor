"""
Multi-track support, layered on top of AudioEditor.

- Track: one timeline lane -- an AudioEditor (reused unmodified) plus
  the state that only makes sense with more than one track: timeline
  position (start_sample), display identity, and mute state.
- MultiTrackSession: owns every Track in the current project and knows
  how to render them all down to one stereo mix via
  mixing.mix_tracks_to_stereo().
"""

import numpy as np
from typing import Optional

from .editor import AudioEditor
from .mixing import mix_tracks_to_stereo

# Palette a new Track cycles through when no explicit color is given,
# so tracks are visually distinguishable on the timeline without the
# person having to pick one manually every time. Matches the accent
# hues already used elsewhere in the app's own palette (violet primary,
# warm amber, plus a couple of additions so 3+ tracks don't repeat).
DEFAULT_TRACK_COLORS = [
    '#8b6ef2',  # violet (app's primary accent)
    '#f2a65e',  # warm amber (app's secondary accent)
    '#5ec4f2',  # sky blue
    '#f25e8f',  # rose
    '#5ef2a6',  # mint
]


class Track:
    """
    One lane in a multi-track session: an AudioEditor (audio + its own
    undo/redo history + selection + effects -- see AudioEditor above,
    completely unmodified and reused as-is) PLUS the state that only
    makes sense once more than one track exists: where this track sits
    on the shared timeline, its display identity, and whether it's
    currently audible.

    Deliberately NOT folded into AudioEditor itself: timeline position
    is a fundamentally different kind of edit than anything AudioEditor
    already tracks. Every other piece of state on AudioEditor describes
    the CONTENT of one buffer (its samples, its selection, what's been
    done to it); start_sample describes this track's PLACEMENT relative
    to every other track. Moving a clip and undoing an effect on that
    clip are different actions a person would expect to work
    independently -- e.g. dragging a track's position shouldn't be on
    the same undo stack as, and shouldn't be undone by, undoing a Reverb
    applied to that track's audio. So start_sample lives here, outside
    AudioEditor's own undo_stack/redo_stack, with its own minimal
    history (see move_to() below) instead.
    """

    def __init__(self, track_id: str, audio: np.ndarray, sample_rate: int,
                 name: str = 'Track', color: Optional[str] = None,
                 start_sample: int = 0):
        self.track_id = track_id
        self.editor = AudioEditor(audio, sample_rate)
        self.name = name
        self.color = color or DEFAULT_TRACK_COLORS[0]
        self.muted = False

        # Timeline position, in samples, at the session's shared sample
        # rate. Always >= 0 -- see mix_tracks_to_stereo()'s docstring
        # for why this has no "unset" sentinel the way a selection does.
        self.start_sample = max(0, int(start_sample))

        # A tiny separate undo history for start_sample ONLY (see class
        # docstring above for why this is deliberately not on
        # self.editor's own undo_stack). Just the previous position --
        # multi-level position undo isn't needed for "I dragged it
        # slightly too far, put it back", and keeping this a single
        # slot rather than a full stack keeps its semantics obvious:
        # one Undo Move always means exactly "go back to right before
        # my last drag", never several drags deep.
        self._prev_start_sample: Optional[int] = None

    def move_to(self, new_start_sample: int):
        """
        Reposition this track's clip on the shared timeline.

        Records the position being LEFT (not the new one) into
        _prev_start_sample, so undo_move() can restore it -- same
        before/after direction as AudioEditor._push_undo(), just with a
        single remembered slot instead of a full stack (see __init__
        docstring for why one slot is the right amount of history here).
        """
        self._prev_start_sample = self.start_sample
        self.start_sample = max(0, int(new_start_sample))

    def undo_move(self) -> bool:
        """
        Undo the last move_to() call, if there was one.

        Returns True if a position was actually restored, False if
        there was nothing to undo (mirrors AudioEditor.undo()'s own
        empty-stack-returns-falsy shape, but as a plain bool since a
        track's own name IS its label -- there's no separate "what
        operation was this" to report the way AudioEditor.undo_label
        needs to for its many different possible operations).
        """
        if self._prev_start_sample is None:
            return False
        self.start_sample, self._prev_start_sample = self._prev_start_sample, None
        return True

    def to_summary_dict(self) -> dict:
        """
        Lightweight JSON-serializable snapshot of this track's
        identity/position -- NOT its audio (that stays as a numpy array
        server-side; the frontend gets waveform peaks or exported audio
        through the same existing per-editor routes, unchanged). Used
        by the track-list route so the frontend can render the timeline
        (names, colors, positions, mute states) without re-fetching
        each track's full audio just to draw the lane headers.
        """
        return {
            'trackId': self.track_id,
            'name': self.name,
            'color': self.color,
            'muted': self.muted,
            'startSample': self.start_sample,
            'startSeconds': self.start_sample / self.editor.sample_rate,
            'durationSeconds': len(self.editor.current) / self.editor.sample_rate,
            'canUndoMove': self._prev_start_sample is not None,
        }


class MultiTrackSession:
    """
    Owns every Track in the current multi-track project, plus the
    shared sample rate every track is assumed to share (see
    mix_tracks_to_stereo()'s docstring on why cross-rate mixing is out
    of scope). Deliberately thin -- adding/removing/looking up tracks
    and building the mix_tracks_to_stereo() input list are the only
    things that need to know about ALL tracks at once; everything else
    (effects, undo, trim, ...) is a single Track's own AudioEditor
    acting alone, reached via get_track(track_id), completely unaware
    that other tracks even exist.
    """

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self.tracks: dict = {}   # track_id -> Track
        self._next_track_num = 1

    def add_track(self, audio: np.ndarray, name: Optional[str] = None,
                  color: Optional[str] = None, start_sample: int = 0) -> Track:
        """
        Create and register a new Track, generating a fresh track_id
        and, if not given, a default name ("Track 1", "Track 2", ...)
        and a color cycled from DEFAULT_TRACK_COLORS.
        """
        track_id = f"track_{self._next_track_num}"
        if name is None:
            name = f"Track {self._next_track_num}"
        if color is None:
            color = DEFAULT_TRACK_COLORS[(self._next_track_num - 1) % len(DEFAULT_TRACK_COLORS)]

        track = Track(track_id, audio, self.sample_rate, name, color, start_sample)
        self.tracks[track_id] = track
        self._next_track_num += 1
        return track

    def get_track(self, track_id: str) -> Optional[Track]:
        return self.tracks.get(track_id)

    def remove_track(self, track_id: str) -> bool:
        """Returns True if a track was actually removed, False if track_id didn't exist."""
        if track_id in self.tracks:
            del self.tracks[track_id]
            return True
        return False

    def list_tracks(self) -> list:
        """
        Track summaries in creation order (dicts preserve insertion
        order since Python 3.7, which is relied on here so the
        frontend's track list doesn't visibly reshuffle between calls).
        """
        return [t.to_summary_dict() for t in self.tracks.values()]

    def mix_down(self, ceiling_db: float = -0.3) -> np.ndarray:
        """
        Render every non-muted track to one stereo buffer via
        mix_tracks_to_stereo() (see its own docstring for the actual
        DSP). Muted tracks are excluded entirely rather than mixed in
        at zero gain -- equivalent for the output audio, but skips
        their contribution to the mix's TIMING too (a muted track that
        happens to be the longest one shouldn't silently extend an
        otherwise-shorter mix with dead air).
        """
        active = [
            {'audio': t.editor.current, 'start_sample': t.start_sample}
            for t in self.tracks.values()
            if not t.muted
        ]
        return mix_tracks_to_stereo(active, self.sample_rate, ceiling_db)
