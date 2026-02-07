import subprocess
import threading
import sys
import re
from Scene import *
import time
import os
from concurrent.futures import ThreadPoolExecutor

class EncodingProcess:

    def __init__(self, source, destination, workers, crop, resolution, start_time, length, source_fps, hdr):
        self.source = source
        self.destination = destination
        self.crop = crop
        self.resolution = resolution
        self.content_start_time = start_time
        self.length = length
        self.source_fps = source_fps
        self.hdr = hdr
        self.max_workers = workers
        self.processing_start_time = time.time()
        # variables
        self.active_workers = 0
        self.progress = 0.0
        self.fps = 0.0
        self.eta = None
        self.passed_time = "--:--:--"
        self.scenes = [Scene(start_time)]

    def start(self):
        sys.stdout.write("\033\n")
        sys.stdout.write("\033\n")
        sys.stdout.write("\033\n")
        scene_detection_process = subprocess.Popen(
            [
                "ffmpeg", "-i", self.source, "-nostdin",
                "-filter:v", "select='gt(scene,0.4)',showinfo",
                "-f", "null", "-"
            ],
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,  # We only care about stderr for showinfo
            text=True,
            errors="replace"
        )
        try:
            for line in iter(scene_detection_process.stderr.readline, ""):
                if '] n:' in line:
                    match = re.search(r"pts_time:(\d+\.\d+)", line)
                    if match:
                        timestamp = float(match.group(1))
                        self.process_timestamp(timestamp)
        finally:
            scene_detection_process.stderr.close()
            scene_detection_process.wait()
            self.scenes[len(self.scenes)-1].end_scene(self.length)
        # bad busy waiting
        while len(self.scenes) > 0:
            while (self.active_workers < self.max_workers) & len(self.scenes) > 0:
                self.update()
            time.sleep(1)
        self.update()
        self.mux()

    def process_timestamp(self, timestamp):
        idx = len(self.scenes) - 1
        if timestamp > self.content_start_time:
            self.scenes[idx].end_scene(timestamp)
            self.scenes.append(Scene(timestamp))
            if not self.scenes[idx].get_length() > 1.0:
                self.scenes[idx].end_scene(None)
                self.scenes.pop(idx+1)
            self.update()

    def update(self):
        sorted_scenes = sorted(
            [s for s in self.scenes if s.is_complete() and not
             s.is_processing],
            key=lambda scene: scene.get_length(), reverse=True
        )
        if len(sorted_scenes) > 0:
            scene = sorted_scenes[0]
            if self.active_workers < self.max_workers:
                self.active_workers = self.active_workers + 1
                scene.is_processing = True
                t = threading.Thread(target=self.worker, args=(scene,))
                t.daemon = True
                t.start()
        if len(self.scenes) > 0:
            if self.scenes[len(self.scenes)-1].is_complete():
                remaining_length = sum(s.get_length() for s in self.scenes if s.is_complete())
                self.progress = min((self.length - remaining_length)/self.length,1.0)
                self.fps = ((self.progress*self.length)/(time.time() - self.processing_start_time))*self.source_fps
                if self.fps > 0:
                    self.eta = time.strftime('%H:%M:%S', time.gmtime(round(((remaining_length*self.source_fps)/self.fps),0)))
                self.passed_time = time.strftime('%H:%M:%S', time.gmtime(time.time()-self.processing_start_time))
            else:
                self.progress = 0.0
            self.updateDisplay()

    def worker(self, scene):
        x, y = self.resolution
        if self.crop:
            filter_complex = "[0:v:0]" + self.crop + ",scale=" + str(x) + ":" + str(y) + "[v]"
        else:
            filter_complex = "[0:v:0]scale=" + str(x) + ":" + str(y) + "[v]"
        subprocess.run(
            ["ffmpeg", "-ss", str(scene.start), "-to", str(scene.end), "-i", self.source, "-nostdin", "-loglevel", "fatal",
             "-filter_complex", filter_complex, "-an", "-map", "[v]",
             "-c:v", "libsvtav1", "-preset", "8", "-pix_fmt", "yuv420p10le", f"chunks/{str(scene.start)}.mp4"], capture_output=True
        )
        self.scenes.remove(scene)
        self.active_workers = self.active_workers - 1

    def updateDisplay(self):
        sys.stdout.write("\033[F" * 3)
        sys.stdout.write(f"\033[KQueue {len(self.scenes)} Workers {self.active_workers}/{self.max_workers}\n")
        sys.stdout.write(f"\033[K{self.resolution[0]}x{self.resolution[1]} {'HDR' if self.hdr else 'SDR'}\n")
        bar_width = 60
        filled = int(self.progress / 1.0 * bar_width)
        bar = "#" * filled + ">" + "-" * (bar_width - filled - 1)
        line = f"[{self.passed_time}] [{bar[:bar_width]}] {round(self.progress*100,1)}% {round(self.fps,1)} fps, eta {self.eta}"
        sys.stdout.write(f"\033[K{line}\n")
        sys.stdout.flush()

    def mux(self):
        file_names = []
        for filename in os.listdir("chunks"):
            if filename.endswith(".mp4"):
                file_names.append(filename)
        file_names.sort(key=lambda f: float(f.replace(".mp4", "")))
        with open('chunks/inputs.txt', 'w') as f:
            for filename in file_names:
                f.write(f"file '{filename}'\n")

        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-loglevel", "fatal",
            "-i", "chunks/inputs.txt",
            "-i", self.source, "-map", "0:v:0",
            "-c:v", "copy",
            "-map", "1:a:0", "-c:a", "libopus", "-b:a", "96k", self.destination
        ]
        subprocess.run(cmd)
        for path in file_names:
            if os.path.exists("chunks/" + path):
                os.remove("chunks/" + path)
        if os.path.exists("chunks/inputs.txt"):
            os.remove("chunks/inputs.txt")
