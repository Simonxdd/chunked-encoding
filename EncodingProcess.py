import threading
import sys
from pathlib import Path
import time
import os
from SceneManager import SceneManager
from src.scene_detection import scene_detection_v2
from src.worker import worker
import subprocess
from src.ConsoleOutput import ConsoleOutput

class EncodingProcess:

    def __init__(self, source, destination, temp_location, workers, crop, resolution, start_time, length, source_fps, hdr, video_coding):
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
        self.video_coding = video_coding
        self.stop_event = threading.Event()
        # variables
        self.passed_time = "--:--:--"
        self.console = ConsoleOutput(self.resolution, self.hdr, self.length, self.source_fps)

    def start(self):
        scene_manager = SceneManager(self.temp_location, self.content_start_time)
        worker_threads = []
        scene_detection_thread = threading.Thread(target=scene_detection_v2, args=(self, scene_manager, self.hdr))
        scene_detection_thread.daemon = True
        ui_thread = threading.Thread(target=self.update_display, args=(worker_threads, scene_manager,))
        try:
            if not scene_manager.scd_finished:
                scene_detection_thread.start()

            for i in range(0, self.max_workers):
                t = threading.Thread(target=worker, args=(self, scene_manager))
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

    def update_display(self, worker_threads, scene_manager):
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
            
            self.console.update_display(
                worker_threads,
                scene_manager,
                self.passed_time,
                total_processed_length,
                progress,
                fps,
                eta
            )
            
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
