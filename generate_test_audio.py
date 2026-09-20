"""
Generate a simple test audio file for the Mini Audio Editor.

Creates a 3-second test tone (440 Hz A note) as a WAV file.
Useful for testing the editor if you don't have audio files handy.
"""

import numpy as np
import soundfile as sf

def generate_test_audio(filename='test_audio.wav', duration=3.0, sample_rate=44100):
    """
    Generate a test audio file with a simple tone.

    Args:
        filename: Output filename
        duration: Duration in seconds
        sample_rate: Sample rate in Hz
    """
    # Generate time axis
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    # Generate a pleasant test signal: A440 Hz with some harmonics
    frequency = 440.0  # A4 note
    signal = 0.3 * np.sin(2 * np.pi * frequency * t)  # Fundamental
    signal += 0.1 * np.sin(2 * np.pi * 2 * frequency * t)  # 2nd harmonic
    signal += 0.05 * np.sin(2 * np.pi * 3 * frequency * t)  # 3rd harmonic

    # Add a simple amplitude envelope to avoid clicks
    envelope = np.ones_like(t)
    fade_samples = int(0.01 * sample_rate)  # 10ms fade
    envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
    envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)

    signal = signal * envelope

    # Write to file
    sf.write(filename, signal, sample_rate)
    print(f"[OK] Generated test audio: {filename}")
    print(f"     Duration: {duration}s")
    print(f"     Sample rate: {sample_rate} Hz")
    print(f"     Frequency: {frequency} Hz (A4 note)")

if __name__ == '__main__':
    generate_test_audio()
    print("\nYou can now load this file in the Mini Audio Editor!")
