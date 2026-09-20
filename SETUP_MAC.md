# 🍏 Mini Audio Editor - Mac Setup Guide

**For:** Mac users receiving this project  
**Date:** August 27, 2026  
**Project:** CSE220 Signals & Linear Systems - Mini Audio Editor

---

## 📋 Prerequisites

Before you begin, make sure you have:
- macOS 10.14 (Mojave) or later
- Internet connection
- Admin access to your Mac
- Terminal access

---

## 🚀 Quick Start (For Experienced Users)

```bash
# Navigate to project folder
cd "Mini Audio Editor"

# Install dependencies
pip3 install -r requirements.txt

# Generate test audio (optional)
python3 generate_test_audio.py

# Run the server
python3 app.py

# Open browser to http://localhost:5000
```

---

## 📖 Detailed Step-by-Step Setup

### Step 1: Check if Python 3 is Installed

1. **Open Terminal** (Applications → Utilities → Terminal)

2. **Check Python version:**
   ```bash
   python3 --version
   ```

3. **Expected output:**
   ```
   Python 3.x.x
   ```
   (where x.x is any version ≥ 3.8)

#### ✅ If Python 3 is installed:
- Continue to **Step 2**

#### ❌ If you see "command not found":
- Continue to **Step 1A: Install Python 3**

---

### Step 1A: Install Python 3 (If Not Installed)

#### Option A: Using Homebrew (Recommended)

1. **Install Homebrew** (if you don't have it):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   
   - Follow the prompts
   - Enter your password when asked
   - Wait for installation (2-5 minutes)

2. **Install Python 3:**
   ```bash
   brew install python
   ```

3. **Verify installation:**
   ```bash
   python3 --version
   ```

#### Option B: Download from Python.org

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download the latest Python 3.x for macOS
3. Run the installer
4. Follow the installation wizard
5. Verify in Terminal: `python3 --version`

---

### Step 2: Navigate to Project Folder

1. **Open Terminal**

2. **Navigate to the project folder:**
   
   If the folder is on your Desktop:
   ```bash
   cd ~/Desktop/"Mini Audio Editor"
   ```
   
   If it's in Downloads:
   ```bash
   cd ~/Downloads/"Mini Audio Editor"
   ```
   
   Or drag-and-drop the folder into Terminal after typing `cd ` (with a space).

3. **Verify you're in the right folder:**
   ```bash
   ls
   ```
   
   **Expected output:**
   ```
   README.md
   app.py
   audio_dsp.py
   generate_test_audio.py
   requirements.txt
   run.bat
   static/
   templates/
   ```

---

### Step 3: Install libsndfile (Audio Library)

The `soundfile` library requires `libsndfile` to read/write audio files.

#### If you have Homebrew:
```bash
brew install libsndfile
```

#### If you DON'T have Homebrew:
You can skip this step and try Step 4. If you get an error about `sndfile`, come back and install Homebrew, then install libsndfile.

---

### Step 4: Install Python Dependencies

1. **Install required packages:**
   ```bash
   pip3 install -r requirements.txt
   ```

2. **Wait for installation** (30-60 seconds)

3. **Expected output:**
   ```
   Successfully installed flask-x.x.x flask-cors-x.x.x numpy-x.x.x soundfile-x.x.x
   ```

#### ⚠️ If you see "pip3: command not found":
Try using `python3 -m pip` instead:
```bash
python3 -m pip install -r requirements.txt
```

#### ⚠️ If you see permission errors:
Add `--user` flag:
```bash
pip3 install --user -r requirements.txt
```

---

### Step 5: Generate Test Audio (Optional)

Generate a 3-second test audio file for immediate testing:

```bash
python3 generate_test_audio.py
```

**Expected output:**
```
[OK] Generated test audio: test_audio.wav
     Duration: 3.0s
     Sample rate: 44100 Hz
     Frequency: 440.0 Hz (A4 note)

You can now load this file in the Mini Audio Editor!
```

---

### Step 6: Start the Flask Server

1. **Run the application:**
   ```bash
   python3 app.py
   ```

2. **Expected output:**
   ```
   ======================================================================
     Mini Audio Editor - CSE220 Signals & Linear Systems Project
   ======================================================================

     Server starting at http://localhost:5000
     Open this URL in your web browser to use the editor.

   ======================================================================

    * Serving Flask app 'app'
    * Debug mode: on
   WARNING: This is a development server. Do not use it in a production deployment.
    * Running on http://127.0.0.1:5000
   Press CTRL+C to quit
   ```

3. **Keep this Terminal window open** - the server must run continuously.

---

### Step 7: Open the Editor in Your Browser

1. **Open your web browser** (Safari, Chrome, Firefox, or Edge)

2. **Navigate to:**
   ```
   http://localhost:5000
   ```
   
   Or:
   ```
   http://127.0.0.1:5000
   ```

3. **You should see:**
   - Header: "🎵 Mini Audio Editor"
   - Button: "📂 Load Audio File"
   - Professional dark-themed interface

---

### Step 8: Test the Editor

1. **Load an audio file:**
   - Click "📂 Load Audio File"
   - Select `test_audio.wav` (or any .wav file)
   - Wait for waveform to appear

2. **Test playback:**
   - Click ▶️ Play button
   - You should hear a 440 Hz tone (musical note A)

3. **Try an effect:**
   - Adjust Gain slider to +6 dB
   - Click "Apply Gain"
   - Audio should become louder

✅ **If everything works - you're all set!**

---

## 🛠️ Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'flask'"

**Solution:**
```bash
pip3 install flask flask-cors numpy soundfile
```

---

### Issue: "ModuleNotFoundError: No module named '_soundfile'"

**Cause:** libsndfile not installed

**Solution:**
```bash
brew install libsndfile
```

If you don't have Homebrew:
```bash
# Install Homebrew first
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Then install libsndfile
brew install libsndfile

# Reinstall soundfile
pip3 uninstall soundfile
pip3 install soundfile
```

---

### Issue: "Address already in use" (Port 5000 taken)

**Cause:** Another app is using port 5000 (common on Mac with AirPlay Receiver)

**Solution 1 - Use a different port:**

Edit `app.py` and change the last line from:
```python
app.run(debug=True, port=5000)
```
to:
```python
app.run(debug=True, port=5001)
```

Then open `http://localhost:5001` instead.

**Solution 2 - Disable AirPlay Receiver:**
1. System Preferences → Sharing
2. Uncheck "AirPlay Receiver"
3. Restart the Flask server

---

### Issue: Browser shows "This site can't be reached"

**Cause:** Flask server isn't running

**Solution:**
1. Check Terminal - is the server running?
2. Look for "Running on http://127.0.0.1:5000"
3. If not, run `python3 app.py` again

---

### Issue: Audio file won't load / "Failed to upload audio file"

**Possible causes & solutions:**

1. **Check browser console:**
   - Press **Cmd+Option+I** (Safari) or **Cmd+Option+J** (Chrome)
   - Look for red error messages
   - Share the error with your teammate

2. **Check Terminal output:**
   - Look for errors in the Terminal where Flask is running
   - Share any error messages

3. **Try a different audio file:**
   - Some formats may not be supported
   - WAV files work best

4. **Hard refresh the browser:**
   - Press **Cmd+Shift+R** to clear cache

---

### Issue: "Permission denied" errors

**Solution:**

Use the `--user` flag when installing:
```bash
pip3 install --user -r requirements.txt
```

Or use a virtual environment:
```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run app
python app.py
```

---

### Issue: No sound during playback

**Solutions:**

1. **Check system volume:**
   - Make sure Mac volume isn't muted
   - Check the volume slider in System Preferences

2. **Check browser permissions:**
   - Safari → Preferences → Websites → Auto-Play
   - Allow audio for localhost

3. **Try a different browser:**
   - Safari, Chrome, Firefox all work

---

## 🔧 Advanced: Using a Virtual Environment (Optional)

For cleaner Python package management:

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# You should see (venv) in your prompt
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py

# When done, deactivate
deactivate
```

**Benefits:**
- Isolated Python packages
- Won't interfere with system Python
- Easy to delete (just remove `venv/` folder)

---

## 📁 Project File Structure

```
Mini Audio Editor/
├── app.py                    # Flask backend server
├── audio_dsp.py              # Core DSP implementations
├── requirements.txt          # Python dependencies
├── README.md                 # Main documentation
├── SETUP_MAC.md             # This file
├── TESTING_GUIDE.md         # Testing instructions
├── generate_test_audio.py   # Test file generator
├── test_audio.wav           # Generated test file
├── run.bat                  # Windows launcher (not used on Mac)
├── templates/
│   └── index.html           # Main UI
└── static/
    ├── style.css            # Styling
    └── app.js               # Frontend logic
```

---

## ⌨️ Keyboard Shortcuts

While using the editor:

- **Cmd+Option+I** (Safari) or **Cmd+Option+J** (Chrome) - Open Developer Console
- **Cmd+R** - Refresh page
- **Cmd+Shift+R** - Hard refresh (clear cache)
- **Cmd+Plus/Minus** - Zoom in/out

In Terminal:
- **Ctrl+C** - Stop Flask server
- **Cmd+K** - Clear Terminal
- **Up Arrow** - Previous command

---

## 🎯 Quick Command Reference

```bash
# Navigate to project
cd ~/Desktop/"Mini Audio Editor"

# Install dependencies
pip3 install -r requirements.txt

# Generate test audio
python3 generate_test_audio.py

# Run server
python3 app.py

# Stop server
# Press Ctrl+C in Terminal

# Check Python version
python3 --version

# Check pip version
pip3 --version

# List installed packages
pip3 list
```

---

## 🐛 Still Having Issues?

1. **Check these files exist:**
   ```bash
   ls -la
   ```
   Make sure you see: `app.py`, `audio_dsp.py`, `requirements.txt`, `static/`, `templates/`

2. **Try reinstalling dependencies:**
   ```bash
   pip3 uninstall flask flask-cors numpy soundfile
   pip3 install -r requirements.txt
   ```

3. **Check Python and pip are working:**
   ```bash
   python3 --version
   pip3 --version
   ```

4. **Contact your teammate** with:
   - Terminal output (copy/paste the errors)
   - Browser console errors (Cmd+Option+J, screenshot the red errors)
   - macOS version (Apple menu → About This Mac)
   - Python version (`python3 --version`)

---

## 📝 Notes for Mac Users

### Differences from Windows:

| Task | Windows | Mac |
|------|---------|-----|
| Run Python | `python` | `python3` |
| Run pip | `pip` | `pip3` |
| Launcher script | `run.bat` | Not needed - use `python3 app.py` |
| Path separator | `\` | `/` |
| Home directory | `C:\Users\username` | `~` or `/Users/username` |

### Mac-Specific Tips:

1. **Terminal shortcut:** Cmd+Space, type "Terminal", press Enter

2. **Find files quickly:**
   ```bash
   # Find the project folder
   find ~ -name "Mini Audio Editor" -type d
   ```

3. **Open folder in Finder from Terminal:**
   ```bash
   open .
   ```

4. **Edit files from Terminal:**
   ```bash
   nano app.py        # Simple editor
   code .             # VS Code (if installed)
   ```

---

## ✅ Success Checklist

After setup, verify:

- [ ] Python 3 is installed and working
- [ ] All dependencies installed successfully
- [ ] `test_audio.wav` generated
- [ ] Flask server starts without errors
- [ ] Browser opens to `http://localhost:5000`
- [ ] Interface loads (dark theme, Load Audio button visible)
- [ ] Can load `test_audio.wav`
- [ ] Waveform appears
- [ ] Playback works (hear 440 Hz tone)
- [ ] Can apply effects (try Gain +6 dB)
- [ ] No errors in Terminal or browser console

**If all checked - you're ready to go!** 🎉

---

## 🎓 For CSE220 Course

This project demonstrates:
- Manual DSP implementations (convolution, gain, fade, reverse)
- LTI system theory (echo via impulse response)
- Signals and linear systems concepts
- Professional audio editing UI

**Key file to review:** `audio_dsp.py` - Contains all manual DSP implementations with detailed math comments.

---

## 📚 Additional Resources

- **Flask Documentation:** https://flask.palletsprojects.com/
- **NumPy Documentation:** https://numpy.org/doc/
- **SoundFile Documentation:** https://python-soundfile.readthedocs.io/
- **WaveSurfer.js:** https://wavesurfer-js.org/

---

## 🤝 Getting Help

If you encounter issues:

1. **Read error messages carefully** - they often tell you exactly what's wrong
2. **Check the TROUBLESHOOTING section** above
3. **Google the error message** - you're probably not the first to encounter it
4. **Contact your teammate** - they set up the project on Windows
5. **Check the README.md** - has additional documentation

---

## 🎉 You're All Set!

Once the editor is running:
1. Read **TESTING_GUIDE.md** for comprehensive testing instructions
2. Read **README.md** for feature documentation
3. Review **audio_dsp.py** for DSP implementation details

**Enjoy editing audio!** 🎵

---

**Last Updated:** August 27, 2026  
**Platform:** macOS (10.14+)  
**Python Required:** 3.8+  
**Tested On:** macOS Ventura, Sonoma
