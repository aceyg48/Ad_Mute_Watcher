import mss
import time
import cv2
import numpy as np

with mss.MSS() as sct:
    for i, mon in enumerate(sct.monitors):
        print(i, mon)

    # Change these to test different spots:
    region = {"left": -2160, "top": 2800, "width": 500, "height": 40}

    shot = np.array(sct.grab(region))
    cv2.imshow("Region Preview", shot)
    cv2.waitKey(0)
    cv2.destroyAllWindows()