import concurrent.futures
import subprocess
import re
import os

import time

def main():
    file_path = None
    scenes = [0.0]
    file_names = []
    starttime = time.time()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    scene_detection_process = subprocess.Popen(
        [
            "ffmpeg", "-i", file_path, "-nostdin",
            "-filter:v", "select='gt(scene,0.4)',showinfo", "-to", "00:01:00",
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
                    scenes.append(timestamp)
                    print(f"Scene detected at: {timestamp}s")
                    file_names.append(f"{str(len(scenes)-2)}.mp4")
                    executor.submit(encode_chunk, scenes[len(scenes)-2], scenes[len(scenes)-1], file_path, len(scenes)-2)
    finally:
        print("Scene detection completed.")
        scene_detection_process.stderr.close()
        scene_detection_process.wait()

    with open('inputs.txt', 'w') as f:
        for filename in file_names:
            f.write(f"file '{filename}'\n")

    executor.shutdown(wait=True)
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-loglevel", "fatal",
        "-i", "inputs.txt",
        "-i", file_path, "-map", "0:v:0",
        "-c:v", "copy",
        "-map", "1:a:0", "-c:a", "libopus", "-b:a", "96k", "output.mp4"
    ]
    subprocess.run(cmd)
    for path in file_names:
        if os.path.exists(path):
            os.remove(path)
    if os.path.exists("inputs.txt"):
        os.remove("inputs.txt")
    endtime = time.time()
    print("Took " + str(endtime - starttime) + " seconds.")


def encode_chunk(start, finish, file_path, i):
    subprocess.run(
        ["ffmpeg", "-ss", str(start), "-to", str(finish), "-i", file_path, "-nostdin", "-loglevel", "fatal",
         "-c:v", "libsvtav1", "-preset", "4", "-pix_fmt", "yuv420p10le", f"{str(i)}.mp4"], capture_output=True
    )
    print("Finished encoding chunk " + str(i))

if __name__ == '__main__':
    main()