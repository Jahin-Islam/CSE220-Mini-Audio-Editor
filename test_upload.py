"""
Test script to verify Flask upload endpoint works correctly.
"""

import requests

def test_upload():
    url = 'http://localhost:5000/api/upload'

    print("[TEST] Testing audio file upload...")

    # Open and upload test_audio.wav
    with open('test_audio.wav', 'rb') as f:
        files = {'file': ('test_audio.wav', f, 'audio/wav')}

        try:
            print("[TEST] Sending POST request to", url)
            response = requests.post(url, files=files)

            print(f"[TEST] Status code: {response.status_code}")
            print(f"[TEST] Response: {response.text[:500]}")

            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    print("[OK] Upload successful!")
                    print(f"  - Duration: {data['duration']:.2f}s")
                    print(f"  - Sample rate: {data['sample_rate']} Hz")
                    print(f"  - Channels: {data['channels']}")
                    print(f"  - Samples: {data['samples']}")
                else:
                    print("[ERROR] Upload failed:", data.get('error'))
                    if 'details' in data:
                        print("[ERROR] Details:", data['details'])
            else:
                print(f"[ERROR] HTTP {response.status_code}")

        except requests.exceptions.ConnectionError:
            print("[ERROR] Cannot connect to server. Is Flask running?")
        except Exception as e:
            print(f"[ERROR] {e}")

if __name__ == '__main__':
    test_upload()
