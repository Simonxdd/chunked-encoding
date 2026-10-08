import platform
import subprocess
import threading

from src.models.config import Config
from src.models.scene_management import SceneManager
from src.ui.console import console

ERROR_LIMIT = 5

def worker(config: Config, stop_event: threading.Event, temp_location, scene_manager: SceneManager):
    while not stop_event.is_set():
        scene, index = scene_manager.request_scene()
        if scene is None:
            break
        try:
            x, y = config.video_attributes.resolution
            if config.video_attributes.crop:
                filter_complex = "[0:v:0]" + config.video_attributes.crop + ",scale=" + str(x) + ":" + str(y) + "[v]"
            else:
                filter_complex = "[0:v:0]scale=" + str(x) + ":" + str(y) + "[v]"
            video_encoding_args = config.video_encoding.get_ffmpeg_args()
            cmd = []
            if config.low_power and platform.system() == "Darwin": cmd.extend(["taskpolicy", "-b"])
            cmd.extend(["ffmpeg"])
            if config.hwaccel: cmd.extend(["-hwaccel", "auto"])
            cmd.extend(["-y", "-ss", str(scene.start), "-to", str(scene.end), "-i", config.input_file, "-nostdin",
                        "-fps_mode", "passthrough", "-enc_time_base", config.video_attributes.time_base,
                    "-loglevel", "warning", "-filter_complex", filter_complex, "-an", "-map", "[v]"
                   ])
            cmd.extend(video_encoding_args)
            if config.ten_bit: cmd.extend(["-pix_fmt", "yuv420p10le"])
            cmd.extend([f"{temp_location / str(index)}.mp4"])
            result = subprocess.run(cmd, capture_output=True, text=True)
            for line in str(result.stderr).split("\n"):
                if config.video_encoding.warning_filter(line):
                    console.print(line)
            if result.returncode == 0:
                scene_manager.scene_finished(scene)
            else:
                if not stop_event.is_set():
                    scene.error_count = scene.error_count + 1
                    console.print(f"FFmpeg error code {result.returncode}:")
                    console.print(result.stderr)
                    if scene.error_count > ERROR_LIMIT:
                        console.print(f"Stopping after {scene.error_count} errors exceeded the limit of {ERROR_LIMIT} errors.")
                        stop_event.set()
        finally:
            scene_manager.release_scene(scene)
