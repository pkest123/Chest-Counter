"""Small bounded screen history for brief toasts while a full scan is busy."""
from collections import deque
import threading
import time
import mss
import numpy as np


def focus_box(notifications, image_width, image_height, actual_width, actual_height):
    if not notifications:
        return None
    item = max(notifications, key=lambda value: value.confidence)
    x1,y1,x2,y2 = item.bounds
    sx,sy = actual_width/image_width, actual_height/image_height
    height = max(12, (y2-y1)*sy)
    # Padding includes a neighbouring XP line and small toast animations.
    padx, pady = max(80,height*3), max(60,height*2)
    left,top = max(0,int(x1*sx-padx)),max(0,int(y1*sy-pady))
    right,bottom = min(actual_width,int(x2*sx+padx)),min(actual_height,int(y2*sy+pady))
    # Never silently lock onto an enormous region or invalid OCR coordinates.
    if right-left<16 or bottom-top<16 or (right-left)*(bottom-top)>min(600000,actual_width*actual_height*.5):
        return None
    return [left,top,right,bottom]


class FocusBuffer:
    def __init__(self, stop, provider):
        self.stop,self.provider = stop,provider
        self.frames = deque(maxlen=40)
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.run,daemon=True)

    def after(self, timestamp, area):
        with self.lock:
            for when, region, frame in self.frames:
                if when>timestamp and region==area:
                    return when,frame
        return None

    def run(self):
        while not self.stop.is_set():
            try:
                with mss.mss() as capture:
                    previous = None
                    while not self.stop.is_set():
                        started = time.monotonic()
                        area = self.provider()
                        if area is None:
                            with self.lock:
                                self.frames.clear()
                            self.stop.wait(.2)
                            continue
                        if area != previous:
                            with self.lock:
                                self.frames.clear()
                            previous = area
                        frame = np.array(capture.grab(area))[:,:,:3].copy()
                        with self.lock:
                            self.frames.append((time.monotonic(),dict(area),frame))
                        self.stop.wait(max(.02,.2-(time.monotonic()-started)))
            except Exception:
                # Buffering is optional; the main capture path remains usable.
                self.stop.wait(1)
