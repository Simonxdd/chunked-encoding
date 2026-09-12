import subprocess
import threading
import signal
import sys
import re
from collections import deque
from pathlib import Path
from Scene import *
import time
import os
from concurrent.futures import ThreadPoolExecutor
from SceneManager import SceneManager

class EncodingProcess:

    def __init__(self, source, destination, temp_location, workers, crop, resolution, start_time, length, source_fps, hdr):
        self.source = source
        self.destination = destination
        self.temp_location = Path(temp_location)
        self.crop = crop
        self.resolution = resolution
        self.content_start_time = start_time
        self.length = length
        self.source_fps = source_fps
        self.hdr = hdr
        self.max_workers = workers
        self.stop_event = threading.Event()
        # variables
        self.passed_time = "--:--:--"

    def start(self):
        scene_manager = SceneManager(self.temp_location, self.content_start_time)
        worker_threads = []
        scene_detection_thread = threading.Thread(target=self.scene_detection, args=(scene_manager,))
        scene_detection_thread.daemon = True
        ui_thread = threading.Thread(target=self.update_display, args=(worker_threads, scene_manager,))
        try:
            if not scene_manager.scd_finished:
                scene_detection_thread.start()

            for i in range(0, self.max_workers):
                t = threading.Thread(target=self.worker, args=(scene_manager,))
                t.start()
                worker_threads.append(t)

            ui_thread.start()

            while scene_detection_thread.is_alive():
                scene_detection_thread.join(timeout=1)
            for t in worker_threads:
                while t.is_alive():
                    t.join(timeout=1)
            self.mux(scene_manager)
            while ui_thread.is_alive():
                ui_thread.join(timeout=1)
        except KeyboardInterrupt:
            self.stop_event.set()
            while ui_thread.is_alive():
                ui_thread.join(timeout=1)
            print("Shutting down... Please consider the temp folder or restart to resume.")
            for t in worker_threads:
                t.join(timeout=1)

    def scene_detection(self, scene_manager):
        if self.crop:
            filter_str = self.crop + ",select='gt(scene,0.25)',showinfo"
        else:
            filter_str = "select='gt(scene,0.25)',showinfo"
        scene_detection_process = subprocess.Popen(
            [
                "ffmpeg", "-i", self.source, "-nostdin",
                "-filter:v", filter_str,
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
                        if timestamp > self.content_start_time:
                            scene_manager.add_scene(timestamp)
        finally:
            scene_detection_process.stderr.close()
            scene_detection_process.wait()
            scene_manager.finish_last_scene(self.length)

    # Global scene cut algorithm written by Gemini
    # Somehow performs marginally worse than a simple threshold with cooldown...?
    # Research further
    def scene_detection_global(self, scene_manager):
        frames = []

        if self.crop:
            filter_str = f"{self.crop},scdet=s=0:t=2,metadata=print,showinfo"
        else:
            filter_str = "scdet=s=0:t=2,metadata=print,showinfo"

        process = subprocess.Popen(
            [
                "ffmpeg", "-i", self.source, "-nostdin",
                "-filter:v", filter_str,
                "-f", "null", "-"
            ],
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True,
            errors="replace"
        )

        current_time = None
        try:
            for line in iter(process.stderr.readline, ""):
                time_match = re.search(r"pts_time:([\d\.]+)", line)
                if time_match:
                    current_time = float(time_match.group(1))
                score_match = re.search(r"lavfi\.scd\.score\s*=\s*([\d\.]+)", line)
                if score_match and current_time is not None:
                    frames.append((current_time, float(score_match.group(1))))
                    current_time = None
        finally:
            process.stderr.close()
            process.wait()

        if not frames:
            scene_manager.finish_last_scene(self.length)
            return

        # 2. Run Global Optimal DP with the tuned cut_penalty of 16.0
        min_len = 1.0
        max_len = 10.0
        cut_penalty = 10.5

        all_frames = [(0.0, 0.0)] + list(frames)
        m = len(all_frames)
        dp = [float('-inf')] * m
        parent = [-1] * m
        dp[0] = 0.0

        window = deque()
        low = 0
        high = 0

        for i in range(1, m):
            t_i, s_i = all_frames[i]

            while low < i and all_frames[low][0] < t_i - max_len:
                low += 1

            while high < i and all_frames[high][0] <= t_i - min_len:
                j = high
                if dp[j] != float('-inf'):
                    while window and dp[window[-1]] <= dp[j]:
                        window.pop()
                    window.append(j)
                high += 1

            while window and window[0] < low:
                window.popleft()

            if window:
                best_j = window[0]
                dp[i] = dp[best_j] + s_i - cut_penalty
                parent[i] = best_j

        last_t = all_frames[-1][0]
        best_end = 0
        max_total = float('-inf')

        for i in range(m):
            if dp[i] != float('-inf') and last_t - all_frames[i][0] <= max_len:
                if dp[i] > max_total:
                    max_total = dp[i]
                    best_end = i

        cuts = []
        curr = best_end
        while curr > 0:
            cuts.append(all_frames[curr])
            curr = parent[curr]
        cuts.reverse()

        # 3. Feed the optimized cuts into the scene manager
        for timestamp, _ in cuts:
            if timestamp > self.content_start_time:
                scene_manager.add_scene(timestamp)

        scene_manager.finish_last_scene(self.length)

    def worker(self, scene_manager):
        while not self.stop_event.is_set():
            scene, index = scene_manager.request_scene()
            if scene is None:
                break
            try:
                x, y = self.resolution
                if self.crop:
                    filter_complex = "[0:v:0]" + self.crop + ",scale=" + str(x) + ":" + str(y) + "[v]"
                else:
                    filter_complex = "[0:v:0]scale=" + str(x) + ":" + str(y) + "[v]"
                result = subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(scene.start), "-to", str(scene.end), "-i", self.source, "-nostdin",
                     "-loglevel", "fatal",
                     "-filter_complex", filter_complex, "-an", "-map", "[v]",
                     "-c:v", "libsvtav1", "-preset", "4", "-pix_fmt", "yuv420p10le",
                     f"{self.temp_location / str(index)}.mp4"], capture_output=True
                )
                if result.returncode == 0:
                    scene_manager.scene_finished(scene)
                else:
                    scene.error_count = scene.error_count + 1
            finally:
                scene_manager.release_scene(scene)

    def update_display(self, worker_threads, scene_manager):
        sys.stdout.write("\033\n")
        sys.stdout.write("\033\n")
        while not self.stop_event.wait(1):
            scenes = scene_manager.scenes
            all_scenes_done_processing = not any(not scene.done_processing for scene in scenes)
            alive_threads = sum(1 for t in worker_threads if t.is_alive())
            total_processed_length = sum(s.get_length() for s in scenes if s.done_processing)
            progress = min(total_processed_length / self.length, 1.0)
            if scene_manager.most_recent_timestamp:
                fps = (scene_manager.finished_length / (scene_manager.most_recent_timestamp - scene_manager.start_timestamp)) * self.source_fps
                eta = time.strftime('%H:%M:%S', time.gmtime(round((((self.length - total_processed_length) * self.source_fps) / fps), 0)))
            else:
                fps = 0
                eta = "--:--:--"
            self.passed_time = time.strftime('%H:%M:%S', time.gmtime(time.time() - scene_manager.start_timestamp))
            sys.stdout.write("\033[F" * 2)
            sys.stdout.write(f"\033[KScenes {sum(1 for s in scenes if s.done_processing)}/{len(scenes)} Workers {alive_threads} ")
            sys.stdout.write(f"\033[K{self.resolution[0]}x{self.resolution[1]} {'HDR' if self.hdr else 'SDR'}\n")
            bar_width = 60
            filled = int(progress / 1.0 * bar_width)
            bar = "#" * filled + ">" + "-" * (bar_width - filled - 1)
            line = f"[{self.passed_time}] [{bar[:bar_width]}] {round(progress*100,1)}% {round(fps,1)} fps, eta {eta}"
            sys.stdout.write(f"\033[K{line}\n")
            sys.stdout.flush()
            if all_scenes_done_processing:
                if alive_threads < 1:
                    break

    def mux(self, scene_manager):
        videos_file = "videos.txt"
        with open(self.temp_location / videos_file, 'w') as f:
            for index, scene in enumerate(scene_manager.scenes):
                f.write(f"file '{index}.mp4'\n")

        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-loglevel", "fatal",
            "-i", self.temp_location / videos_file, "-ss", str(self.content_start_time),
            "-i", self.source, "-map", "0:v:0",
            "-c:v", "copy",
            "-map", "1:a:0", "-c:a", "libopus", "-b:a", "96k", self.destination
        ]
        subprocess.run(cmd)
        try:
            pass
            scene_manager.clean_up()
            os.remove(self.temp_location / videos_file)
            for index, scene in enumerate(scene_manager.scenes):
                os.remove(self.temp_location / (str(index) + ".mp4"))
            os.rmdir(self.temp_location)
        except Exception:
            sys.exit("Unexpected error deleting temporary files. Please check the temporary folder " + str(self.temp_location))