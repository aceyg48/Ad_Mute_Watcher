# Import standard libraries for pattern matching, time delays, Windows audio/COM integration, and command line argument parsing
import re
import time
from ctypes import POINTER, cast
import argparse

# Import computer vision and image processing libraries
import cv2
import mss
import numpy as np
import pytesseract
from comtypes import CLSCTX_ALL, CoInitialize

# Import Windows audio API wrapper
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

# Set path to Tesseract OCR executable (required for text recognition from screenshots)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ===== CONFIGURATION =====
# Monitor selection (None = auto-detect leftmost portrait monitor)
MONITOR_INDEX = None

# Keywords that identify an advertisement (converted to lowercase for matching)
AD_KEYWORDS = [
    "advertisement",
    "sponsored"
]

# How frequently to check the screen regions (in seconds)
SCAN_INTERVAL_SECONDS = 0.6

# Number of consecutive detections required to change mute state (prevents flicker/false positives)
CONSECUTIVE_HITS_REQUIRED = 2

# Print debug output showing OCR results
DEBUG_OCR = True


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug-ocr", dest="debug_ocr", action="store_true")
    parser.add_argument("--no-debug-ocr", dest="debug_ocr", action="store_false")
    parser.set_defaults(debug_ocr=DEBUG_OCR)
    return parser.parse_args()

def get_endpoint_volume():
    """Get access to the Windows system audio volume control."""
    CoInitialize()
    speakers = AudioUtilities.GetSpeakers()

    # Modern pycaw exposes this as a property
    if hasattr(speakers, "EndpointVolume"):
        return speakers.EndpointVolume

    # Fallback for older pycaw versions
    activate = getattr(speakers, "Activate", None) or getattr(speakers, "activate", None)
    if activate is None:
        raise RuntimeError("Could not get audio endpoint volume from pycaw.")

    # Activate the audio interface and cast to volume control
    interface = activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def set_muted(volume, muted: bool):
    """Mute or unmute system audio if state has changed."""
    current = bool(volume.GetMute())
    if current != muted:
        # Only call SetMute if the state is actually different
        volume.SetMute(int(muted), None)
        print("MUTED (ad detected)" if muted else "UNMUTED (song/content detected)")


def extract_text_from_region(sct, region) -> str:
    """
    Capture a screen region and extract text using OCR.
    
    Args:
        sct: mss screen capture object
        region: dict with left, top, width, height keys
    
    Returns:
        Extracted text as string
    """
    # Grab the screen pixels in the specified region
    shot = np.array(sct.grab(region))
    
    # Convert BGRA color image to grayscale for better OCR
    gray = cv2.cvtColor(shot, cv2.COLOR_BGRA2GRAY)

    # Apply preprocessing to improve OCR accuracy
    gray = cv2.GaussianBlur(gray, (3, 3), 0)  # Blur to reduce noise
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)  # Convert to pure black/white

    # Run Tesseract OCR with PSM 7 (treat as single text line)
    text = pytesseract.image_to_string(bw, config="--psm 7")
    return text.strip()


def normalize_text(s: str) -> str:
    """Convert text to lowercase and remove special characters for matching."""
    # Keep only letters, numbers, and spaces; convert to lowercase
    return re.sub(r"[^a-z0-9\s]", " ", s.lower()).strip()


def is_ad_text(text: str) -> bool:
    """Check if extracted text contains any ad keywords."""
    normalized = normalize_text(text)
    # Return True if any keyword is found in the normalized text
    return any(k in normalized for k in AD_KEYWORDS)


def main():
    """Main loop: continuously monitor screen regions and control mute based on ad detection."""
    print("Starting ad mute watcher. Press Ctrl+C to stop.")
    print(f"Ad keywords: {AD_KEYWORDS}")

    # Get access to system volume control
    volume = get_endpoint_volume()
    
    # Start screen capture session
    with mss.MSS() as sct:
        # Debug: print all available monitors and their positions
        print("Available monitors:")
        for i, mon in enumerate(sct.monitors):
            print(i, mon)

        # Filter to only portrait-oriented monitors (height > width)
        physical = sct.monitors[1:]  # Skip virtual desktop (index 0)
        portrait = [m for m in physical if m["height"] > m["width"]]

        # Error if no portrait monitor found
        if not portrait:
            raise RuntimeError("No portrait monitor found.")

        # Select the leftmost portrait monitor (smallest x-coordinate)
        mon = min(portrait, key=lambda m: m["left"])

        # Define two screen regions to scan for ad text (in case ads appear in multiple spots)
        REGIONS = [
            {"left": -2160, "top": 2800, "width": 500, "height": 40},  # Region 1
            {"left": -2160, "top": 2835, "width": 500, "height": 40},  # Region 2
        ]

        print(f"Using monitor: {mon}")
        print(f"Watching regions: {REGIONS}")

        # Counters for consecutive ad/content detections
        ad_hits = 0
        content_hits = 0
        ad_state = None  # None=unknown, True=ad, False=content

        # Main monitoring loop
        while True:
            # Extract text from both regions
            texts = [extract_text_from_region(sct, r) for r in REGIONS]
            
            # Check if ANY region contains ad keywords
            ad_now = any(is_ad_text(t) for t in texts)

            # Print OCR results if debug mode is on
            if DEBUG_OCR:
                print(" | ".join([f"R{i+1}:{t!r}" for i, t in enumerate(texts)]) + f" | ad={ad_now}")

            # Increment appropriate counter (reset the other)
            if ad_now:
                ad_hits += 1
                content_hits = 0
            else:
                content_hits += 1
                ad_hits = 0

            # Change mute state if consecutive hits threshold is reached
            if ad_hits >= CONSECUTIVE_HITS_REQUIRED and ad_state is not True:
                ad_state = True
                set_muted(volume, True)
            elif content_hits >= CONSECUTIVE_HITS_REQUIRED and ad_state is not False:
                ad_state = False
                set_muted(volume, False)

            # Wait before next scan
            time.sleep(SCAN_INTERVAL_SECONDS)

 
if __name__ == "__main__":
    args = parse_args()
    DEBUG_OCR = args.debug_ocr

    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
