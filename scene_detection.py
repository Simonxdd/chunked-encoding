import subprocess
import re
from collections import deque

def scene_detection(instance, scene_manager):
    if instance.crop:
        filter_str = instance.crop + ",select='gt(scene,0.25)',showinfo"
    else:
        filter_str = "select='gt(scene,0.25)',showinfo"
    scene_detection_process = subprocess.Popen(
        [
            "ffmpeg", "-i", instance.source, "-nostdin",
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
                    if timestamp > instance.content_start_time:
                        scene_manager.add_scene(timestamp)
    finally:
        scene_detection_process.stderr.close()
        scene_detection_process.wait()
        scene_manager.finish_last_scene(instance.length)


# Global scene cut algorithm written by Gemini
# Somehow performs marginally worse than a simple threshold with cooldown...?
# Research further
def scene_detection_global(instance, scene_manager):
    frames = []

    if instance.crop:
        filter_str = f"{instance.crop},scdet=s=0:t=2,metadata=print,showinfo"
    else:
        filter_str = "scdet=s=0:t=2,metadata=print,showinfo"

    process = subprocess.Popen(
        [
            "ffmpeg", "-i", instance.source, "-nostdin",
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
        scene_manager.finish_last_scene(instance.length)
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
        if timestamp > instance.content_start_time:
            scene_manager.add_scene(timestamp)

    scene_manager.finish_last_scene(instance.length)
