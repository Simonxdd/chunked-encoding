import subprocess

def worker(instance, scene_manager):
    while not instance.stop_event.is_set():
        scene, index = scene_manager.request_scene()
        if scene is None:
            break
        try:
            x, y = instance.resolution
            if instance.crop:
                filter_complex = "[0:v:0]" + instance.crop + ",scale=" + str(x) + ":" + str(y) + "[v]"
            else:
                filter_complex = "[0:v:0]scale=" + str(x) + ":" + str(y) + "[v]"
            video_encoding_args = instance.video_coding.get_ffmpeg_args()
            cmd = ["ffmpeg", "-y", "-ss", str(scene.start), "-to", str(scene.end), "-i", instance.source, "-nostdin",
                    "-loglevel", "warning", "-pix_fmt", "yuv420p10le",
                    "-filter_complex", filter_complex, "-an", "-map", "[v]"
                   ]
            cmd.extend(video_encoding_args)
            cmd.extend([f"{instance.temp_location / str(index)}.mp4"])
            result = subprocess.run(cmd, capture_output=True, text=True)
            for line in str(result.stderr).split("\n"):
                if instance.video_coding.warning_filter(line):
                    print(line)
            if result.returncode == 0:
                scene_manager.scene_finished(scene)
            else:
                scene.error_count = scene.error_count + 1
                print(result.stderr)
        finally:
            scene_manager.release_scene(scene)
