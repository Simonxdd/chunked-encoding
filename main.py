import os
import subprocess
import sys
import threading
from pathlib import Path
import hashlib
import base64
import shutil

from src.models.config import Config, parse_cli_args
from src.worker import worker
from src.scene_detection import scene_detection_v2

from src.models.video import VideoAttributes
from src.models.scene_management import SceneManager
from src.ui.console import console


def main():
    if not shutil.which("ffmpeg"): sys.exit("FFmpeg was not found on this system.")

    args = parse_cli_args()

    stop_event = threading.Event()
    ui_thread = threading.Thread(target=console.display_routine, args=(stop_event,))
    ui_thread.start()

    try:
        config = Config(args)
    except Exception as e:
        console.print(e)
        stop_event.set()
        sys.exit(1)
    temp_location = Path(get_file_hash(config))
    if not Path(temp_location).exists(): os.mkdir(temp_location)

    scene_manager = SceneManager(temp_location, 0)

    scene_detection_thread = threading.Thread(target=scene_detection_v2, args=(config.video_attributes, scene_manager, stop_event))

    worker_threads = []
    try:
        if not scene_manager.scd_finished:
            scene_detection_thread.start()

        for i in range(0, config.workers):
            t = threading.Thread(target=worker, args=(config, stop_event, temp_location, scene_manager))
            t.start()
            worker_threads.append(t)

        console.start(scene_manager, config, worker_threads)

        while scene_detection_thread.is_alive():
            scene_detection_thread.join(timeout=1)
        for t in worker_threads:
            while t.is_alive():
                t.join(timeout=1)
        console.stop()
        if not stop_event.is_set():
            mux(scene_manager, temp_location, config, config.output_file)
            console.print("Encoding finished.")
        stop_event.set()
        while ui_thread.is_alive():
            ui_thread.join(timeout=1)
    except KeyboardInterrupt:
        console.print("Shutting down... Please consider the temp folder or restart to resume.")
        stop_event.set()
        while ui_thread.is_alive():
            ui_thread.join(timeout=1)
        for t in worker_threads:
            t.join(timeout=1)

def mux(scene_manager: SceneManager, temp_location: Path, config: Config, destination: Path):
    video = config.video_attributes
    audio = config.audio_mappings
    videos_file = "videos.txt"
    with open(temp_location / videos_file, 'w') as f:
        for index, scene in enumerate(scene_manager.scenes):
            f.write(f"file '{index}{scene_manager.FILE_ENDING}'\n")

    cmd = [
        "ffmpeg", "-y", "-loglevel", "fatal",
        "-i", str(video.source), "-f", "concat",
        "-safe", "0", "-i", str(temp_location / videos_file),
        "-map", "1:v:0", "-c:v", "copy",
    ]
    cmd.extend(audio.audio_args)
    cmd.append(str(destination))
    subprocess.run(cmd)
    try:
        pass
        scene_manager.clean_up()
        os.remove(temp_location / videos_file)
        for index, scene in enumerate(scene_manager.scenes):
            os.remove(temp_location / (str(index) + scene_manager.FILE_ENDING))
        os.rmdir(temp_location)
    except Exception:
        console.print("Unexpected error deleting temporary files. Please check the temporary folder " + str(temp_location))

def get_file_hash(config):
    stat = os.stat(config.input_file)
    sha_256 = hashlib.sha256()

    # Only hashing the name, size and mdate should be adequate
    sha_256.update(str(config.input_file).encode())
    sha_256.update(str(stat.st_size).encode())
    sha_256.update(str(stat.st_mtime).encode())

    sha_256.update(str(config.ten_bit).encode())
    sha_256.update(str(repr(config.video_attributes)).encode())
    sha_256.update(str(repr(config.video_encoding)).encode())
    digest = sha_256.digest()
    return "temp-" + base64.urlsafe_b64encode(digest).decode('utf-8').rstrip('=')

if __name__ == '__main__':
    main()
