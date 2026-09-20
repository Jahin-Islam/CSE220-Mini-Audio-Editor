# 🧪 Mini Audio Editor - Complete Testing Checklist

**Project:** CSE220 Signals & Linear Systems - Mini Audio Editor  
**Date:** August 27, 2026  
**Purpose:** Comprehensive manual testing guide to verify all functionality

---

## 📋 Pre-Testing Setup

### ✅ Prerequisites
- [ ] Flask server is running (`python app.py` or `run.bat`)
- [ ] Browser is open to `http://localhost:5000`
- [ ] Test audio file (`test_audio.wav`) is available
- [ ] Browser console is open (Press F12 → Console tab)
- [ ] No errors in browser console on page load

### Expected Initial State
- **UI Elements Visible:**
  - Header: "🎵 Mini Audio Editor"
  - "Load Audio File" button
- **UI Elements Hidden:**
  - Waveform section
  - Playback controls
  - Editing tools
  - Action bar (undo/redo/export)

---

## 🎵 Test 1: Load Audio File

### Steps:
1. Click **"📂 Load Audio File"** button
2. Select `test_audio.wav` from the file picker
3. Wait for loading overlay to disappear

### Expected Results:
✅ **Loading Overlay:**
- Displays "Loading audio file..." with spinner
- Disappears after 1-2 seconds

✅ **UI Changes:**
- Audio info appears below load button:
  - Filename: `test_audio.wav`
  - Duration: `0:03` (3 seconds)
  - Sample Rate: `44100 Hz`
  - Channels: `Mono`
  - Samples: `132,300`

✅ **Waveform Display:**
- Blue waveform appears in the waveform section
- Waveform shows clear oscillations (sinusoidal pattern)
- Waveform fills the container horizontally
- Height varies with amplitude

✅ **Playback Section:**
- Play button visible
- Stop button visible
- Time display shows: `0:00 / 0:03`

✅ **Tools Section:**
- All tool cards are visible and enabled
- Sliders are interactive

✅ **Action Bar:**
- Undo, Redo, Reset, Export buttons visible

✅ **Toast Notification:**
- Green notification: "Audio loaded successfully!"
- Auto-disappears after 3 seconds

✅ **Browser Console:**
- `[DEBUG] File selected: test_audio.wav Size: 264644`
- `[DEBUG] Sending upload request...`
- `[DEBUG] Response status: 200`
- `[DEBUG] Response data: {success: true, ...}`
- No errors

✅ **Flask Terminal:**
- `[DEBUG] Upload request received`
- `[DEBUG] File size: 264644 bytes`
- `[DEBUG] Audio loaded: 132300 samples at 44100 Hz`
- `POST /api/upload 200`

### ❌ Failure Indicators:
- "Failed to upload audio file" error
- Waveform doesn't appear
- JavaScript errors in console
- Flask errors in terminal

---

## ▶️ Test 2: Playback Controls

### Test 2A: Play Audio

#### Steps:
1. Click **▶️ Play** button

#### Expected Results:
✅ **Playback:**
- Audio plays (440 Hz A note, pleasant tone with harmonics)
- Duration: 3 seconds
- Volume: moderate, clear

✅ **Visual Feedback:**
- Play button changes to **⏸️ Pause**
- Blue progress overlay moves across waveform left-to-right
- Red vertical cursor line moves across waveform
- Current time updates: `0:00` → `0:01` → `0:02` → `0:03`

✅ **Sound Quality:**
- **Tone:** Pure, musical A note (440 Hz)
- **Quality:** Clear, no distortion, no clicks
- **Fade:** Smooth start and end (no pops)
- **Volume:** Comfortable listening level

### Test 2B: Pause/Resume

#### Steps:
1. While playing, click **⏸️ Pause**
2. Click **▶️ Play** again

#### Expected Results:
✅ Audio pauses mid-playback
✅ Play button changes back to **▶️ Play**
✅ Current time freezes
✅ Clicking Play resumes from same position

### Test 2C: Stop

#### Steps:
1. While playing, click **⏹️ Stop**

#### Expected Results:
✅ Audio stops immediately
✅ Current time resets to `0:00`
✅ Waveform cursor returns to start
✅ Play button shows **▶️ Play**

### Test 2D: Playback After End

#### Steps:
1. Let audio play to completion (0:03)

#### Expected Results:
✅ Playback stops automatically
✅ Button changes to **▶️ Play**
✅ Cursor returns to start
✅ Current time shows `0:00`

---

## 🎯 Test 3: Region Selection

### Steps:
1. **Click and hold** on the waveform at ~0.5 seconds
2. **Drag** to ~2.5 seconds
3. **Release** mouse button

### Expected Results:
✅ **Visual Feedback:**
- Semi-transparent blue rectangle appears during drag
- Selected region has light blue overlay: `rgba(74, 158, 255, 0.3)`
- Region has draggable handles on left and right edges

✅ **Selection Info:**
- Below waveform shows:
  ```
  Selected: 0:00 - 0:02 (Duration: 0:02)
  ```
  (Exact times depend on your selection)

✅ **Region Behavior:**
- Only ONE region allowed at a time
- Creating a new region removes the previous one
- Can resize region by dragging handles
- Can move region by dragging the middle

### Test Multiple Selections:
1. Create a region
2. Create another region elsewhere

#### Expected:
✅ First region disappears
✅ Only the new region remains

---

## ✂️ Test 4: Trim to Selection

### Steps:
1. Load `test_audio.wav`
2. Select a region from ~0.5s to ~2.5s (middle 2 seconds)
3. Click **✂️ Trim to Selection**

### Expected Results:
✅ **Loading Overlay:** "Trimming audio..."

✅ **Waveform Changes:**
- Waveform becomes shorter
- Shows only the selected portion
- Duration updates to ~`0:02` (2 seconds)

✅ **Audio Info Updates:**
- Duration: `0:02` (2 seconds)
- Samples: ~88,200 (depends on exact selection)

✅ **Playback:**
- Playing the trimmed audio plays only the selected portion
- Duration matches new length

✅ **Sound:**
- Same 440 Hz tone
- Starts partway through the note
- Ends partway through

✅ **Toast:** "Audio trimmed successfully!"

### Test Without Selection:
1. Click Trim without selecting a region

#### Expected:
✅ Toast: "Please select a region first by dragging on the waveform"

---

## 🔗 Test 5: Join Audio

### Steps:
1. Load `test_audio.wav` (Duration: 0:03)
2. Click **🔗 Join Audio**
3. Select `test_audio.wav` again

### Expected Results:
✅ **Loading Overlay:** "Joining audio files..."

✅ **Waveform Changes:**
- Waveform becomes longer (2× original length)
- Duration updates to `0:06` (6 seconds)
- Samples: 264,600 (double original)

✅ **Playback:**
- Playing audio plays first clip, then immediately second clip
- Total duration: 6 seconds
- Seamless transition (no gap or click between clips)

✅ **Sound:**
- First 3 seconds: 440 Hz tone
- Brief silence/transition
- Next 3 seconds: same 440 Hz tone

✅ **Toast:** "Audio files joined successfully!"

---

## ⏮️ Test 6: Reverse

### Test 6A: Reverse All

#### Steps:
1. Load `test_audio.wav`
2. Click **⏮️ Reverse All**

#### Expected Results:
✅ **Loading Overlay:** "Reversing audio..."

✅ **Waveform Changes:**
- Waveform appears mirrored horizontally
- Right side becomes left side, left becomes right

✅ **Playback:**
- Audio plays backwards
- Duration: still 0:03

✅ **Sound:**
- **Different from original!**
- Starts with fade-out (was fade-in)
- Ends with fade-in (was fade-out)
- Tone still 440 Hz but envelope is reversed
- Sounds slightly "wrong" or "backwards"

✅ **Toast:** "Audio reversed successfully!"

### Test 6B: Reverse Selection

#### Steps:
1. Load `test_audio.wav`
2. Select middle 1 second (0:01 to 0:02)
3. Click **⏮️ Reverse Selection**

#### Expected Results:
✅ Waveform shows middle portion flipped
✅ Playing audio: normal start → reversed middle → normal end
✅ Sound: noticeable discontinuity in the middle section
✅ Toast: "Audio reversed successfully!"

---

## 🔊 Test 7: Gain / Volume

### Test 7A: Increase Gain (+6 dB)

#### Steps:
1. Load `test_audio.wav`
2. Move **Gain slider** to `+6`
3. Observe slider value display updates to `+6 dB`
4. Click **Apply Gain**

#### Expected Results:
✅ **Loading Overlay:** "Applying gain..."

✅ **Waveform Changes:**
- Waveform amplitude increases (taller waves)
- Waveform appears approximately 2× taller

✅ **Playback:**
- Audio is noticeably LOUDER
- +6 dB ≈ doubling the amplitude
- Sound should be roughly twice as loud

✅ **Sound Quality:**
- Still clear, no distortion (original is quiet enough)
- Same 440 Hz tone, just louder

✅ **Toast:** "Gain of +6 dB applied successfully!"

### Test 7B: Decrease Gain (-6 dB)

#### Steps:
1. Load fresh `test_audio.wav`
2. Set Gain slider to `-6`
3. Click **Apply Gain**

#### Expected Results:
✅ Waveform becomes shorter (smaller amplitude)
✅ Audio is noticeably QUIETER
✅ -6 dB ≈ halving the amplitude
✅ Sound should be roughly half as loud
✅ Toast: "Gain of -6 dB applied successfully!"

### Test 7C: Extreme Gain (+20 dB)

#### Steps:
1. Load fresh `test_audio.wav`
2. Set Gain to `+20`
3. Click **Apply Gain**

#### Expected Results:
✅ Waveform is VERY tall
✅ Audio is MUCH LOUDER
✅ +20 dB ≈ 10× amplitude
✅ May sound slightly distorted if clipping occurs
✅ Be careful: may be uncomfortably loud!

### Test 7D: Zero Gain (0 dB)

#### Steps:
1. Load audio, apply 0 dB gain

#### Expected:
✅ No change (0 dB = no change)
✅ Waveform identical
✅ Volume identical

---

## 🌅 Test 8: Fade In

### Steps:
1. Load `test_audio.wav`
2. Set **Fade Duration** to `1.0` seconds
3. Set **Curve** to `Smooth (Cosine)`
4. Click **Apply Fade In**

### Expected Results:
✅ **Loading Overlay:** "Applying fade in..."

✅ **Waveform Changes:**
- First ~1 second of waveform starts at zero amplitude
- Gradually increases to full amplitude
- Creates a "ramp" effect on the left side

✅ **Playback:**
- Audio starts silent
- Gradually fades in over first 1 second
- Reaches full volume by 1:00

✅ **Sound:**
- Smooth volume increase from 0 to full
- No clicks or pops
- 440 Hz tone emerges gradually
- Professional fade-in effect

✅ **Toast:** "Fade in applied successfully!"

### Test Different Curves:

#### Linear Fade:
1. Load fresh audio
2. Set Curve to `Linear`
3. Apply Fade In

#### Expected:
✅ Fade is more "linear" (constant rate of increase)
✅ Less smooth than cosine
✅ Still no clicks

---

## 🌅 Test 9: Fade Out

### Steps:
1. Load `test_audio.wav`
2. Set **Fade Duration** to `1.0` seconds
3. Set **Curve** to `Smooth (Cosine)`
4. Click **Apply Fade Out**

### Expected Results:
✅ **Waveform Changes:**
- Last ~1 second of waveform decreases to zero
- Creates a "ramp down" effect on the right side

✅ **Playback:**
- Audio plays normally for first 2 seconds
- Gradually fades out over last 1 second
- Ends in silence (no abrupt cut)

✅ **Sound:**
- 440 Hz tone at full volume
- Smoothly decreases to silence
- No clicks or pops at the end
- Professional fade-out effect

✅ **Toast:** "Fade out applied successfully!"

---

## 🔄 Test 10: Echo Effect (Convolution)

### ⚠️ Important Note
**Echo uses manual convolution** - may take 3-10 seconds to process!

### Test 10A: Single Echo (200ms delay)

#### Steps:
1. Load `test_audio.wav`
2. Set **Delay:** `200` ms
3. Set **Decay:** `0.5`
4. Set **Echoes:** `1`
5. Click **Apply Echo**

#### Expected Results:
✅ **Loading Overlay:** "Applying echo (convolution in progress)..."
✅ **Processing Time:** 3-10 seconds (manual convolution is slow)

✅ **Waveform Changes:**
- Waveform appears slightly "thicker"
- Hard to see visually (echo adds to original)

✅ **Playback:**
- Duration: still 0:03 (truncated to original length)

✅ **Sound - VERY DISTINCTIVE:**
- **Original tone plays**
- **0.2 seconds later, hear a REPEAT of the tone** at half volume
- Effect: "tone... tone" (like room echo)
- Clear double sound
- Second tone is quieter (50% = decay 0.5)

✅ **Audio Characteristics:**
- Still 440 Hz tone
- Echo is same frequency, just delayed and quieter
- Sounds like playing in a small room with one echo
- No distortion

✅ **Toast:** "Echo effect applied successfully!"

### Test 10B: Multiple Echoes (3 echoes)

#### Steps:
1. Load fresh `test_audio.wav`
2. Set Delay: `250` ms
3. Set Decay: `0.6`
4. Set **Echoes: `3`**
5. Apply Echo

#### Expected Results:
✅ **Processing Time:** 5-15 seconds (convolution with longer impulse response)

✅ **Sound - MULTIPLE REPEATS:**
- **Original tone**
- **0.25s later:** First echo at 60% volume
- **0.50s later:** Second echo at 36% volume (0.6²)
- **0.75s later:** Third echo at 21.6% volume (0.6³)
- Effect: "tone... tone.. tone. tone" (like canyon echo)
- Each echo progressively quieter
- Sounds like a reverberant space

### Test 10C: Short Delay (50ms)

#### Steps:
1. Delay: `50` ms
2. Decay: `0.7`
3. Echoes: `2`
4. Apply Echo

#### Expected:
✅ Echoes happen very quickly (0.05s apart)
✅ Sounds more like "thickening" or "doubling" than distinct echoes
✅ Creates a "fuller" sound

### Test 10D: Long Delay (500ms)

#### Steps:
1. Delay: `500` ms
2. Decay: `0.4`
3. Echoes: `2`
4. Apply Echo

#### Expected:
✅ Echoes are spaced far apart (half a second)
✅ Very obvious distinct repeats
✅ Sounds like large hall or canyon

---

## ↶ Test 11: Undo

### Steps:
1. Load `test_audio.wav`
2. Apply Gain +6 dB
3. Click **↶ Undo**

### Expected Results:
✅ **Loading Overlay:** "Undoing..."

✅ **Waveform Reverts:**
- Returns to state before gain was applied
- Amplitude back to original

✅ **Playback:**
- Volume back to original level

✅ **Toast:** "Undo successful!"

### Test Multiple Undos:
1. Load audio
2. Apply Gain +6 dB
3. Apply Fade In 1s
4. Apply Echo 200ms
5. Click Undo (removes echo)
6. Click Undo (removes fade in)
7. Click Undo (removes gain)

#### Expected:
✅ Each undo removes one operation
✅ Operations removed in reverse order (stack behavior)
✅ After 3 undos, back to original audio

### Test Undo With No History:
1. Load audio
2. Click Undo (nothing to undo)

#### Expected:
✅ Toast: "Nothing to undo"
✅ No changes

---

## ↷ Test 12: Redo

### Steps:
1. Load audio
2. Apply Gain +6 dB
3. Click Undo
4. Click **↷ Redo**

### Expected Results:
✅ Gain +6 dB is re-applied
✅ Waveform amplitude increases again
✅ Toast: "Redo successful!"

### Test Redo After New Operation:
1. Load audio
2. Apply Gain +6 dB
3. Undo
4. Apply Fade In
5. Try to Redo

#### Expected:
✅ Toast: "Nothing to redo"
✅ Redo stack cleared after new operation

---

## 🔄 Test 13: Reset to Original

### Steps:
1. Load `test_audio.wav`
2. Apply multiple operations:
   - Gain +10 dB
   - Fade In 1s
   - Fade Out 1s
   - Echo 200ms
3. Click **🔄 Reset to Original**
4. Confirm in dialog

### Expected Results:
✅ **Confirmation Dialog:** "Reset to original audio? This will clear the undo history."

✅ **After Confirming:**
- Waveform returns to original state
- All effects removed
- Duration, amplitude, everything restored
- Playback sounds like original test_audio.wav

✅ **Undo Stack Cleared:**
- Clicking Undo does nothing
- Toast: "Nothing to undo"

✅ **Toast:** "Reset to original audio!"

---

## 👁️ Test 14: Before/After Comparison

### Steps:
1. Load `test_audio.wav`
2. Apply Gain +10 dB
3. Click **👁️ eye icon** above waveform

### Expected Results:
✅ **Second Waveform Appears:**
- Below the edited waveform
- Gray/darker color (#888888)
- Shows ORIGINAL audio (before gain)
- Smaller amplitude than edited version

✅ **Visual Comparison:**
- Top waveform: tall waves (after +10 dB)
- Bottom waveform: shorter waves (original)
- Easy to see the difference

✅ **Toast:** "Comparison mode: Original (bottom) vs Edited (top)"

### Toggle Off:
1. Click eye icon again

#### Expected:
✅ Original waveform disappears
✅ Only edited waveform remains
✅ Toast: "Comparison mode disabled"

---

## 💾 Test 15: Export Audio

### Steps:
1. Load `test_audio.wav`
2. Apply some effects (e.g., Gain +6 dB, Echo 200ms)
3. Click **💾 Export WAV**

### Expected Results:
✅ **Loading Overlay:** "Exporting audio..."

✅ **File Download:**
- Browser downloads file named `edited_audio.wav`
- File size: depends on effects applied
- Downloaded to browser's default download folder

✅ **Toast:** "Audio exported successfully!"

### Verify Exported File:
1. Open exported file in a media player (Windows Media Player, VLC, etc.)
2. Play it

#### Expected:
✅ File plays correctly
✅ Contains all applied effects
✅ Duration matches edited duration
✅ Sound quality preserved
✅ No corruption

### Try Loading Exported File:
1. Click Load Audio File
2. Select the exported `edited_audio.wav`

#### Expected:
✅ Loads successfully
✅ Waveform matches what you exported
✅ Can apply more effects to it

---

## 🔬 Test 16: Edge Cases & Error Handling

### Test 16A: Load Invalid File

#### Steps:
1. Click Load Audio File
2. Select a non-audio file (e.g., .txt, .jpg, .pdf)

#### Expected:
✅ Loading overlay appears
✅ Error toast: "Error: [description]"
✅ Flask terminal shows error
✅ UI remains in initial state (no waveform)

### Test 16B: Very Short Selection

#### Steps:
1. Load audio
2. Select a TINY region (< 0.1 seconds)
3. Try to trim

#### Expected:
✅ Should work, but result is very short audio
✅ May be hard to hear
✅ Waveform very small

### Test 16C: Apply Multiple Operations in Sequence

#### Steps:
1. Load audio
2. Gain +6 dB
3. Fade In 0.5s
4. Fade Out 0.5s
5. Echo 150ms
6. Reverse All

#### Expected:
✅ Each operation works
✅ Effects stack/accumulate
✅ Final result has all effects applied
✅ Can undo each one individually

### Test 16D: Rapidly Click Operations

#### Steps:
1. Load audio
2. Click Apply Gain multiple times rapidly

#### Expected:
✅ Operations queue or are ignored while processing
✅ No crashes
✅ UI remains responsive

---

## 📊 Performance Tests

### Test 17A: Long Audio File

If you have a longer audio file (e.g., 30+ seconds):

#### Expected:
✅ Load time: 2-5 seconds
✅ Waveform renders (may take a moment)
✅ Playback works smoothly
✅ Operations take longer:
  - Gain: <1 second
  - Fade: 1-2 seconds
  - Echo: **10-30+ seconds** (convolution is O(N·M))

### Test 17B: Echo on Long Audio

**Warning: This will be SLOW!**

#### Steps:
1. Load 30-second audio
2. Apply Echo with 3 echoes

#### Expected:
✅ Processing time: 20-60+ seconds
✅ Loading overlay stays visible
✅ Eventually completes
✅ This demonstrates the O(N·M) complexity of manual convolution

---

## ✅ Complete Test Summary

### Critical Tests (MUST PASS):
- [ ] Test 1: Load Audio
- [ ] Test 2: Playback Controls
- [ ] Test 7: Gain
- [ ] Test 10: Echo Effect
- [ ] Test 11: Undo
- [ ] Test 15: Export

### Important Tests:
- [ ] Test 3: Region Selection
- [ ] Test 4: Trim
- [ ] Test 5: Join
- [ ] Test 6: Reverse
- [ ] Test 8: Fade In
- [ ] Test 9: Fade Out
- [ ] Test 12: Redo
- [ ] Test 13: Reset
- [ ] Test 14: Comparison

### Nice-to-Have Tests:
- [ ] Test 16: Edge Cases
- [ ] Test 17: Performance

---

## 🎯 Expected Sound Summary

### Original test_audio.wav:
- **Frequency:** 440 Hz (musical note A4)
- **Duration:** 3 seconds
- **Quality:** Pure, clear tone with harmonics
- **Envelope:** Smooth fade in/out to prevent clicks

### After Gain +6 dB:
- **Louder** (approximately 2× amplitude)
- Still clear and pure

### After Fade In 1s:
- Starts silent, gradually increases to full volume
- Smooth transition

### After Fade Out 1s:
- Ends gradually, fades to silence
- No abrupt cut

### After Echo 200ms, decay 0.5:
- Original tone followed by a repeat 0.2s later
- Repeat is half as loud
- Distinctive "room echo" effect

### After Reverse:
- Sounds "backwards"
- Fade envelope is flipped
- Frequency still 440 Hz but progression feels wrong

---

## 🐛 Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| "Failed to upload" | WaveSurfer.js not loading | Hard refresh (Ctrl+Shift+R) |
| No sound on playback | Browser audio blocked | Check browser audio settings |
| Echo takes forever | Normal for manual convolution | Wait patiently (3-30+ seconds) |
| Waveform doesn't appear | JavaScript error | Check browser console (F12) |
| "Nothing to undo" | No operations performed | Apply an operation first |
| Can't select region | Drag selection not enabled | Reload page, try again |

---

## 🎓 For Oral Defense

When demonstrating to professors:

1. **Load audio** - Show the waveform appears
2. **Play audio** - Demonstrate playback works
3. **Apply Echo** - Emphasize this uses **manual convolution**
4. **Show before/after** - Use comparison mode
5. **Explain the math** - Point to code comments in `audio_dsp.py`

**Key Points:**
- Echo demonstrates LTI system theory
- Convolution is implemented manually (no np.convolve)
- Each DSP operation has mathematical formula in code
- UI is professional and feature-rich

---

## ✅ Sign-Off

After completing all critical tests:

- [ ] All features work as expected
- [ ] No JavaScript errors in console
- [ ] No Flask errors in terminal
- [ ] Audio quality is good
- [ ] Echo effect is clearly audible
- [ ] Export produces valid WAV files
- [ ] UI is responsive and polished

**Project Status:** ✅ READY FOR SUBMISSION

**Tested By:** _________________  
**Date:** _________________  
**Result:** PASS / FAIL  

---

**Happy Testing! 🎵**
