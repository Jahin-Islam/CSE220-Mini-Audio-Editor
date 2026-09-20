"""
Audio Repair: click removal and edit-splice repair, both built on the
same cubic-Hermite-spline "bridge across a gap" primitive.

- _hermite_bridge: shared reconstruction step — matches value AND
  slope at both ends of a gap so the patched segment is inaudible.
- declick_channel: detects short, bipolar, isolated transient spikes
  (vinyl pops, mouth clicks) via an adaptive derivative-floor detector.
- repair_splice_channel: detects abrupt DC/energy discontinuities from
  a hard edit splice, which declick's spike detector would miss.
"""

import numpy as np
from typing import Tuple

def _hermite_bridge(x: list, s: int, e: int) -> None:
    """
    Smoothly bridge samples x[s:e] (in place) with a cubic Hermite spline
    that matches the signal's VALUE and SLOPE at both endpoints, so the
    replacement segment blends in with no audible seam:

        H(t) = h00(t)*x0 + h10(t)*m0*span + h01(t)*x1 + h11(t)*m1*span

    where t in [0,1] is the normalized position across the gap, x0/x1 are
    the samples just outside the gap, m0/m1 are slope estimates there
    (central difference), and h00,h10,h01,h11 are the four standard cubic
    Hermite basis functions. This is the exact interpolation AudioMass
    uses to patch over both declicked spikes and repaired splices -- it
    is a genuine signal-reconstruction technique (matching value +
    derivative at the boundary of a gap), not just linear crossfading.

    Mutates `x` (a plain Python list) directly across indices [s, e).
    """
    if e <= s:
        return
    x0 = x[s - 1]
    x1 = x[e]
    m0 = 0.5 * (x[s] - x[s - 2])
    m1 = 0.5 * (x[e + 1] - x[e - 1])
    span = e - (s - 1)
    for jj in range(s, e):
        t = (jj - (s - 1)) / span
        t2 = t * t
        t3 = t2 * t
        h00 = 2 * t3 - 3 * t2 + 1
        h10 = t3 - 2 * t2 + t
        h01 = -2 * t3 + 3 * t2
        h11 = t3 - t2
        x[jj] = h00 * x0 + h10 * m0 * span + h01 * x1 + h11 * m1 * span


def declick_channel(audio: np.ndarray, sample_rate: int, sensitivity: str = 'medium') -> Tuple[np.ndarray, int]:
    """
    Click Reduction: find and smooth over short transient clicks (vinyl
    pops, mouth clicks) by detecting isolated, bipolar, brief spikes in
    the sample-to-sample derivative and interpolating across them.

    Algorithm (same shape detector as AudioMass's deClickChannel):
    1. Track a running (EMA) estimate of the "normal" derivative
       magnitude -- how much the signal usually changes sample to
       sample -- as a noise/edge floor that adapts as the signal's
       loudness/character changes over time.
    2. A click candidate starts wherever |x[i]-x[i-1]| jumps far above
       that adaptive floor (and above an absolute noise floor, so
       silence doesn't false-trigger).
    3. From there, walk forward while consecutive derivative samples
       stay above 40% of the trigger height. This traces out the click's
       width. A true click is:
         - short (`w < maxW`, ~2ms at this sample rate -- true clicks
           are brief; slow real transients like a drum hit are not)
         - "bipolar" -- the derivative swings both positive AND negative
           within the window (a real click looks like a spike UP then
           DOWN, unlike e.g. a rising edge, which only goes one way)
       This combination (short + bipolar + not hitting the max window)
       is what separates an actual click from a normal fast musical
       transient.
    4. Bridge the click (plus a small `margin` on each side) using a
       cubic Hermite spline (see _hermite_bridge) that matches the
       signal's value and slope just outside the gap, so the repair is
       inaudible.

    Args:
        audio: Input audio array (1-D, mono)
        sample_rate: Sampling rate in Hz
        sensitivity: 'low' | 'medium' | 'high' -- higher sensitivity
            catches more/smaller clicks but risks touching real transients

    Returns:
        (repaired_audio, num_clicks_fixed)
    """
    x = audio.tolist()
    n = len(x)
    if n < 128:
        return audio.copy(), 0

    k = {'low': 6, 'high': 3}.get(sensitivity, 4)
    max_w = max(8, int(sample_rate * 0.002))
    min_w = 2
    margin = 2
    abs_floor = {'low': 0.03, 'high': 0.008}.get(sensitivity, 0.015)

    boot = min(2048, n)
    ema = sum(abs(x[i] - x[i - 1]) for i in range(1, boot)) / max(boot - 1, 1)
    ema = max(ema, 1e-4)
    alpha = 1.0 / 2048

    count = 0
    i = 4
    while i < n - max_w - 4:
        sd = x[i] - x[i - 1]
        d = abs(sd)
        if d > ema * k and d > abs_floor:
            thresh = d * 0.4
            end = i + 1
            max_end = i + max_w
            pos_max, neg_max = sd, sd
            while end < max_end and abs(x[end] - x[end - 1]) > thresh:
                dd = x[end] - x[end - 1]
                if dd > pos_max:
                    pos_max = dd
                if dd < neg_max:
                    neg_max = dd
                end += 1
            w = end - i
            hit_max = end >= max_end
            bipolar = pos_max > thresh and -neg_max > thresh

            if w >= min_w and not hit_max and bipolar:
                s = max(i - margin, 2)
                e = min(end + margin, n - 2)
                _hermite_bridge(x, s, e)
                count += 1
                i = e + 4
                continue

        ema = ema * (1 - alpha) + d * alpha
        ema = max(ema, 1e-4)
        i += 1

    return np.array(x), count


def repair_splice_channel(audio: np.ndarray, sample_rate: int, sensitivity: str = 'medium') -> Tuple[np.ndarray, int]:
    """
    Edit Repair: find and smooth over abrupt edit-point discontinuities
    (e.g. a hard cut/splice between two takes with different DC
    offset/level) that a simple click detector would miss, because the
    jump itself may be small -- what gives it away is a sustained shift
    in the local DC level and energy right after the jump.

    Algorithm (same shape detector as AudioMass's repairSpliceChannel):
    1. Same adaptive derivative-floor tracking as declick_channel(), but
       tuned for a slower/steadier discontinuity rather than a sharp
       spike.
    2. A candidate splice point is a derivative jump that is "isolated"
       (nothing similarly large in the next ~20 samples -- rules out a
       genuinely fast musical passage, which would keep moving).
    3. At a candidate, compare `dcW`-sample (~20ms) windows immediately
       before and after: their mean (DC offset) and variance (energy).
       It is judged a real edit splice, not a normal signal feature, if
       ALL of:
         - the DC shift is in the same direction as the initial jump
           (`sameDir`)
         - the shift is large enough to matter (`absDc > dcFloor` and
           `> half the jump size`)
         - the two windows' energy (variance) is "balanced" -- neither
           side is wildly louder/quieter than the other (`hiV < loV*4`),
           which rules out e.g. a fade-in/fade-out (real level changes
           tend to have very different variance) and favors an actual
           flat splice between two similarly-leveled takes
    4. Bridge across the splice with the same cubic Hermite spline used
       by declick_channel().

    Args:
        audio: Input audio array (1-D, mono)
        sample_rate: Sampling rate in Hz
        sensitivity: 'low' | 'medium' | 'high'

    Returns:
        (repaired_audio, num_splices_fixed)
    """
    x = audio.tolist()
    n = len(x)
    if n < 512:
        return audio.copy(), 0

    k = {'low': 8, 'high': 4}.get(sensitivity, 6)
    abs_floor = {'low': 0.05, 'high': 0.015}.get(sensitivity, 0.025)
    dc_floor = {'low': 0.04, 'high': 0.008}.get(sensitivity, 0.018)
    dc_w = max(256, int(sample_rate * 0.020))
    fade_w = max(16, int(sample_rate * 0.004))
    half_fade = fade_w // 2

    boot = min(2048, n)
    ema = sum(abs(x[i] - x[i - 1]) for i in range(1, boot)) / max(boot - 1, 1)
    ema = max(ema, 1e-4)
    alpha = 1.0 / 2048

    count = 0
    i = dc_w + half_fade + 4
    limit = n - dc_w - half_fade - 4
    while i < limit:
        d = x[i] - x[i - 1]
        abs_d = abs(d)

        if abs_d > ema * k and abs_d > abs_floor:
            isolated = True
            for ck in range(1, 21):
                if i + ck >= n:
                    break
                dd = x[i + ck] - x[i + ck - 1]
                if abs(dd) > abs_d * 0.5:
                    isolated = False
                    break

            if isolated:
                pre_mean = post_mean = pre_e = post_e = 0.0
                for j in range(1, dc_w + 1):
                    pv = x[i - j]
                    pov = x[i + j - 1]
                    pre_mean += pv
                    post_mean += pov
                    pre_e += pv * pv
                    post_e += pov * pov
                pre_mean /= dc_w
                post_mean /= dc_w
                dc_diff = post_mean - pre_mean
                abs_dc = abs(dc_diff)
                same_dir = (d > 0 and dc_diff > 0) or (d < 0 and dc_diff < 0)
                pre_var = pre_e / dc_w - pre_mean * pre_mean
                post_var = post_e / dc_w - post_mean * post_mean
                lo_v = min(pre_var, post_var)
                hi_v = max(pre_var, post_var)
                balanced = lo_v > 1e-6 and hi_v < lo_v * 4

                if same_dir and balanced and abs_dc > dc_floor and abs_dc > abs_d * 0.5:
                    s = max(i - half_fade, 2)
                    e = min(i + half_fade, n - 2)
                    _hermite_bridge(x, s, e)
                    count += 1
                    i = e + dc_w
                    continue

        ema = ema * (1 - alpha) + abs_d * alpha
        ema = max(ema, 1e-4)
        i += 1

    return np.array(x), count
