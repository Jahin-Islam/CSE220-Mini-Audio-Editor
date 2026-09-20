# 🎵 Mini Audio Editor

**CSE220 Signals & Linear Systems Course Project**

A professional desktop audio editor built with Flask, WaveSurfer.js, and manual DSP implementations. Features a modern dark-themed UI with real-time waveform visualization, drag-to-select regions, and comprehensive audio editing tools including convolution-based echo effects.

---

## 📋 Project Overview

This audio editor demonstrates core concepts from signals and linear systems theory:

- **Manual DSP implementations** (no library shortcuts for core algorithms)
- **LTI system analysis** through convolution-based effects
- **Time-domain signal processing**
- **Before/after comparison** for understanding signal transformations

### Key Features

✅ **File Operations**
- Load audio files (.wav, .flac, .ogg, etc.)
- Export edited audio as .wav
- Join multiple audio clips

✅ **Waveform Visualization**
- Interactive waveform display powered by WaveSurfer.js
- Drag-to-select regions on the waveform
- Before/after comparison overlay
- Real-time playback with progress indicator

✅ **Editing Operations**
- **Trim**: Cut audio to selected region
- **Reverse**: Reverse entire clip or just selection
- **Gain/Volume**: Adjustable gain with dB display (-20 to +20 dB)
- **Fade In/Out**: Linear or smooth (raised cosine) fades
- **Echo Effect**: Convolution-based echo with adjustable delay, decay, and repetitions

✅ **Workflow Features**
- Undo/redo stack (unlimited history)
- Reset to original audio
- Playback controls (play, pause, stop)

---

## 🔬 Manual DSP Implementations

### Core Course Requirements (Manually Implemented)

These operations are implemented from mathematical first principles **without using library shortcuts** (e.g., no `np.convolve`, `scipy.signal.convolve`, etc.) to demonstrate understanding of the underlying algorithms for oral defense:

#### 1. **Discrete Convolution** (`discrete_convolution`)
```python
# Direct implementation: y[n] = Σ x[k]·h[n-k]
def discrete_convolution(x, h):
    for n in range(y_len):
        for k in range(M):
            if 0 <= n - k < N:
                y[n] += x[n - k] * h[k]
```

#### 2. **Echo Impulse Response** (`create_echo_impulse`)
```python
# LTI system impulse response: h[n] = δ[n] + α·δ[n-D] + α²·δ[n-2D] + ...
# where δ[n] is the unit impulse, D is delay, α is decay factor
```

#### 3. **Gain/Scale** (`apply_gain`)
```python
# Sample-wise multiplication: y[n] = a·x[n]
# where a = 10^(gain_dB/20)
```

#### 4. **Fade In/Out** (`apply_fade`)
```python
# Multiplicative envelope: y[n] = g[n]·x[n]
# Linear: g[n] = n/N (fade in) or (N-n)/N (fade out)
# Cosine: g[n] = 0.5*(1 - cos(π·n/N)) (fade in)
```

#### 5. **Reverse** (`reverse_audio`)
```python
# Manual index reversal: y[n] = x[N-1-n]
```

### Standard Array Operations (Not DSP Algorithms)

These use straightforward array operations as they are data manipulations, not signal processing algorithms:

- **Trim**: Array slicing `audio[start:end]`
- **Join**: Array concatenation `np.concatenate([audio1, audio2])`

### LTI System Theory: Echo Effect

The echo effect directly demonstrates **Linear Time-Invariant (LTI) system** theory:

1. **Model echo as an LTI system** with impulse response:
   ```
   h[n] = δ[n] + α·δ[n-D] + α²·δ[n-2D] + α³·δ[n-3D] + ...
   ```
   where:
   - `δ[n]` = unit impulse (Kronecker delta)
   - `D` = delay in samples
   - `α` = decay factor (0 < α < 1)

2. **Apply convolution**: `y[n] = x[n] * h[n]` using manual discrete convolution

3. **Result**: Each echo is a delayed, attenuated copy of the input — exactly what convolution with this impulse response predicts.

---

## 🚀 Setup & Installation

### Prerequisites

- **Python 3.8+** (tested with Python 3.10)
- **pip** (Python package manager)

### Installation Steps

1. **Navigate to the project directory:**
   ```bash
   cd "P:\Coding Practice\Python\Python Signal Project\Mini Audio Editor"
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

   This installs:
   - `flask` — Web server framework
   - `flask-cors` — Cross-Origin Resource Sharing support
   - `numpy` — Array operations (storage only, not used for DSP algorithms)
   - `soundfile` — Audio file I/O (.wav reading/writing)

3. **Run the application:**
   ```bash
   python app.py
   ```

4. **Open in your web browser:**
   ```
   http://localhost:5000
   ```

   The application will open in your default browser with the audio editor interface.

---

## 📖 Usage Guide

### 1. Load Audio

- Click **"📂 Load Audio File"** button
- Select a `.wav` file (or `.flac`, `.ogg` if supported by your system)
- The waveform will display automatically
- Audio info (duration, sample rate, channels) appears below the load button

### 2. Select Region

- **Click and drag** on the waveform to select a region
- Selection info (start, end, duration) displays below the waveform
- Use selections for **Trim** or **Reverse Selection** operations

### 3. Edit Operations

#### Basic Operations
- **Trim to Selection**: Cuts the audio to only the selected region
- **Reverse All**: Reverses the entire audio clip
- **Reverse Selection**: Reverses only the selected region
- **Join Audio**: Loads a second file and appends it to the current clip

#### Gain/Volume
- Adjust the **Gain** slider (-20 to +20 dB)
- Click **Apply Gain** to scale the amplitude
- 0 dB = no change, +6 dB ≈ double amplitude, -6 dB ≈ half amplitude

#### Fade In/Out
- Set **Duration** (0.1 to 5.0 seconds)
- Choose **Curve**: Smooth (Cosine) or Linear
- Click **Apply Fade In** (affects start) or **Apply Fade Out** (affects end)

#### Echo Effect (Convolution)
- **Delay**: Time between echoes (50-1000 ms)
- **Decay**: Echo volume reduction factor (0.1-0.9)
- **Echoes**: Number of echo repetitions (1-8)
- Click **Apply Echo** to convolve with the impulse response
- ⚠️ **Note**: Convolution can be slow for long audio files (this is expected with manual implementation)

### 4. Playback

- **▶️ Play/Pause**: Start or pause playback
- **⏹️ Stop**: Stop playback and return to start
- **Time display**: Shows current position and total duration

### 5. Undo/Redo/Reset

- **↶ Undo**: Revert the last operation (unlimited undo history)
- **↷ Redo**: Re-apply the last undone operation
- **🔄 Reset to Original**: Discard all edits and return to the originally loaded audio

### 6. Before/After Comparison

- Click the **👁️ eye icon** above the waveform
- The original waveform displays below the edited waveform (grayed out)
- Compare changes visually
- Click again to hide the comparison

### 7. Export

- Click **💾 Export WAV** to download the edited audio
- File saves as `edited_audio.wav` in your browser's download folder

---

## 📁 Project Structure

```
Mini Audio Editor/
│
├── app.py                  # Flask backend (API endpoints, server)
├── audio_dsp.py            # Core DSP module (manual implementations)
├── requirements.txt        # Python dependencies
├── README.md              # This file
│
├── templates/
│   └── index.html         # Main HTML interface
│
└── static/
    ├── style.css          # Professional dark theme styling
    └── app.js             # Frontend JavaScript (WaveSurfer.js, UI logic)
```

### File Descriptions

- **`audio_dsp.py`**: Contains all manual DSP implementations with detailed mathematical comments. This is the core module for oral defense.

- **`app.py`**: Flask web server that provides REST API endpoints for audio operations. Acts as a bridge between the UI and DSP module.

- **`templates/index.html`**: Main HTML interface with WaveSurfer.js integration for professional waveform display.

- **`static/style.css`**: Modern dark theme with audio editor aesthetic (inspired by professional DAWs).

- **`static/app.js`**: Frontend logic for UI interactions, API calls, waveform management, and playback control.

---

## 🎓 For Oral Defense / Viva

### Questions You Might Be Asked

**Q: Explain your convolution implementation.**

**A:** I implemented discrete convolution directly from the definition:
```
y[n] = Σ_{k=0}^{M-1} x[k]·h[n-k]
```
Using nested loops: outer loop iterates over each output sample `n`, inner loop sums over all `k` where both `x[n-k]` and `h[k]` are valid indices. This is the time-domain convolution formula from the textbook.

**Q: Why is convolution used for echo?**

**A:** Echo is a Linear Time-Invariant (LTI) system. Any LTI system can be fully characterized by its impulse response. For echo, the impulse response is a series of delayed, decaying impulses (the original sound plus attenuated copies at delay intervals). When we convolve the input signal with this impulse response, we get the output — which is exactly the echo effect. This demonstrates the fundamental LTI property: output = input ⊛ impulse response.

**Q: What's the time complexity of your convolution?**

**A:** O(N·M) where N is the input length and M is the impulse response length. For each of N output samples, we perform M multiply-accumulate operations. This is slower than FFT-based convolution (O(N log N)), but demonstrates the direct time-domain implementation clearly.

**Q: Explain the fade in/out envelope.**

**A:** Fade is a time-varying gain applied sample-wise: `y[n] = g[n]·x[n]` where `g[n]` is the envelope function. For linear fade in, `g[n] = n/N` (ramps from 0 to 1). For smooth fade in, I used a raised cosine: `g[n] = 0.5·(1 - cos(πn/N))`, which has continuous first derivative so there's no audible "click" at the boundaries.

**Q: What's the difference between your manual implementations and using library functions?**

**A:** Libraries like `np.convolve()` or `scipy.signal` provide optimized, production-ready implementations using techniques like FFT or SIMD vectorization. My implementations use the direct mathematical definitions with explicit loops, making the algorithm transparent for educational purposes. The library versions are faster but hide the underlying math — mine are slower but demonstrate understanding of the theory.

### Key Points to Emphasize

✅ **All core DSP operations are manually implemented** from mathematical definitions
✅ **Echo demonstrates LTI system theory** through impulse response and convolution
✅ **Each function has detailed mathematical comments** for clarity
✅ **Numpy is used only for array storage**, not for DSP operations themselves
✅ **File I/O uses soundfile** — this is standard practice, not a DSP shortcut

---

## 🛠️ Technical Stack

### Backend
- **Python 3.8+**
- **Flask** — Web framework
- **NumPy** — Array storage (not used for DSP algorithms)
- **SoundFile** — Audio file I/O

### Frontend
- **HTML5** / **CSS3** — Modern responsive UI
- **JavaScript (ES6+)** — Client-side logic
- **WaveSurfer.js v7** — Professional waveform visualization
- **WaveSurfer Regions Plugin** — Drag-to-select functionality

---

## 📊 Performance Notes

- **Convolution speed**: Manual convolution is O(N·M) complexity. For long audio files (>30 seconds) or many echo repetitions, expect a few seconds of processing time. This is normal for unoptimized educational implementations.

- **Waveform rendering**: Downsamples to ~5000 points for smooth visualization while preserving detail.

- **Browser playback**: Uses HTML5 Audio API with base64-encoded WAV data for instant playback without additional file downloads.

---

## 🐛 Troubleshooting

### "No module named 'flask'"
→ Run `pip install -r requirements.txt`

### "Address already in use" error
→ Another process is using port 5000. Either:
- Stop the other process
- Or change the port in `app.py`: `app.run(debug=True, port=5001)`

### Audio file won't load
→ Ensure the file is a valid audio format (.wav recommended). Check browser console (F12) for error messages.

### Convolution is very slow
→ This is expected for manual implementation. Try:
- Shorter audio clips
- Fewer echo repetitions
- Smaller delay values

### Waveform doesn't display
→ Check that browser supports HTML5 Canvas and Web Audio API. Use a modern browser (Chrome, Firefox, Edge, Safari).

---

## 🎯 Course Credit Summary

### Manually Implemented DSP (for course requirements):
1. ✅ **Discrete convolution** — Direct definition, nested loops
2. ✅ **Echo impulse response** — Manual construction from delayed impulses
3. ✅ **Gain/scale** — Sample-wise multiplication with dB conversion
4. ✅ **Fade in/out** — Manual envelope construction (linear/cosine)
5. ✅ **Reverse** — Manual index reversal

### Standard Operations (not DSP algorithms per se):
- Trim — Array slicing
- Join — Array concatenation

### Libraries Used ONLY For:
- **NumPy** — Array storage and basic operations
- **SoundFile** — File I/O (reading/writing .wav files)
- **Flask** — Web server infrastructure
- **WaveSurfer.js** — Waveform visualization (frontend only, not DSP)

**NO libraries were used as shortcuts for the core DSP operations themselves.**

---

## 📝 License

This project is created for educational purposes as part of CSE220 Signals and Linear Systems course requirements.

---

## 👨‍💻 Author

Created for CSE220 course project demonstration.

**Date:** August 2026

---

## 🙏 Acknowledgments

- Course: **CSE220 - Signals and Linear Systems**
- Waveform visualization: **WaveSurfer.js**
- UI inspiration: Modern professional DAWs (digital audio workstations)

---

**Enjoy editing audio and exploring signal processing! 🎵**
