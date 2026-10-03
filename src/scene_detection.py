import subprocess
import re
import threading
from collections import deque

from src.models.scene_management import SceneManager
from src.models.video import VideoAttributes

# min and max length based on recommended AV1 keyints.
MIN_LEN = 1.0
MAX_LEN = 10.0
LOOKAHEAD_WINDOW = 60.0

def scene_detection_v2(video: VideoAttributes, scene_manager: SceneManager, stop_event: threading.Event):
    """
    Smarter scene detection using rolling-window dynamic programming.
    Written with the help of generative AI.
    """
    #TODO: Evaluate more precise cost functions for SDR and HDR
    cut_penalty = 5.0 if video.hdr else 9.5

    buffer = []
    last_cut_time = 0.0

    def evaluate_and_commit_buffer(is_eof=False):
        nonlocal last_cut_time, buffer

        while buffer:
            active_frames = [(t, s) for t, s in buffer if t > last_cut_time]
            if not active_frames:
                break

            latest_time = active_frames[-1][0]

            # In streaming mode, wait until active frames span the full lookahead window
            if not is_eof and (latest_time - last_cut_time < LOOKAHEAD_WINDOW):
                break

            nodes = [(last_cut_time, 0.0)] + active_frames
            horizon_limit = last_cut_time + LOOKAHEAD_WINDOW

            cuts = _solve_penalized_dp(
                nodes=nodes,
                min_len=MIN_LEN,
                max_len=MAX_LEN,
                cut_penalty=cut_penalty,
                horizon_limit=horizon_limit,
                is_eof=is_eof
            )

            if not cuts:
                break

            if is_eof:
                # EOF FLUSH: Commit ALL remaining cuts in the optimal path
                for cut_time, _ in cuts:
                    if cut_time > video.start_time:
                        scene_manager.add_scene(cut_time)
                buffer.clear()
                break
            else:
                # STREAMING: Commit ONLY the first cut in the optimal path
                first_cut_time, _ = cuts[0]
                if first_cut_time > video.start_time:
                    scene_manager.add_scene(first_cut_time)

                last_cut_time = first_cut_time
                buffer = [(t, s) for t, s in buffer if t > last_cut_time]
                # Loop continues if remaining buffer still spans >= LOOKAHEAD_WINDOW

    # 1. Read FFmpeg frame scores and process in rolling windows
    for timestamp, score in _stream_ffmpeg_scdet_scores(video, stop_event):
        buffer.append((timestamp, score))
        if buffer[-1][0] - last_cut_time >= LOOKAHEAD_WINDOW:
            evaluate_and_commit_buffer(is_eof=False)

    if stop_event.is_set():
        return

    # 2. Flush remaining buffer and commit all tail cuts at EOF
    evaluate_and_commit_buffer(is_eof=True)
    scene_manager.finish_last_scene(video.length)

def _stream_ffmpeg_scdet_scores(video: VideoAttributes, stop_event: threading.Event):
    """Executes FFmpeg and yields (timestamp, scdet_score) tuples as they are parsed."""
    if video.crop:
        filter_str = f"{video.crop},scdet=s=0:t=2,metadata=print,showinfo"
    else:
        filter_str = "scdet=s=0:t=2,metadata=print,showinfo"

    process = subprocess.Popen(
        [
            "ffmpeg", "-hwaccel", "auto", "-i", video.source, "-nostdin",
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
        for line in process.stderr:
            if stop_event.is_set():
                break
            time_match = re.search(r"pts_time:([\d\.]+)", line)
            if time_match:
                current_time = float(time_match.group(1))

            score_match = re.search(r"lavfi\.scd\.score\s*=\s*([\d\.]+)", line)
            if score_match and current_time is not None:
                yield current_time, float(score_match.group(1))
                current_time = None
    finally:
        process.stderr.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
        process.wait()

def _solve_penalized_dp(nodes, min_len, max_len, cut_penalty, horizon_limit=None, is_eof=False):
    """
    Computes optimal cut locations using sliding-window Dynamic Programming.
    Returns a list of selected cut node tuples: [(timestamp, score), ...].
    """
    num_nodes = len(nodes)
    if num_nodes <= 1:
        return []

    dp = [float('-inf')] * num_nodes
    parent = [-1] * num_nodes
    dp[0] = 0.0

    # Monotonic deque maintaining indices of candidate cut points
    window = deque()
    low = 0
    high = 0

    for i in range(1, num_nodes):
        t_i, s_i = nodes[i]

        # Slide lower bound: candidates must be within max_len of current frame
        while low < i and nodes[low][0] < t_i - max_len:
            low += 1

        # Slide upper bound: candidates must be at least min_len before current frame
        while high < i and nodes[high][0] <= t_i - min_len:
            j = high
            if dp[j] != float('-inf'):
                while window and dp[window[-1]] <= dp[j]:
                    window.pop()
                window.append(j)
            high += 1

        # Remove expired indices from deque
        while window and window[0] < low:
            window.popleft()

        # Select candidate that maximizes cumulative DP score
        if window:
            best_j = window[0]
            dp[i] = dp[best_j] + s_i - cut_penalty
            parent[i] = best_j

    # Choose optimal trajectory endpoint
    best_end = -1
    max_total = float('-inf')

    if is_eof:
        # At EOF: Ensure the tail scene (from final cut to end of video) is <= max_len
        video_end_time = nodes[-1][0]
        best_end = 0  # 0 means no additional cut is needed if remaining tail <= max_len
        for i in range(num_nodes):
            if dp[i] != float('-inf') and (video_end_time - nodes[i][0] <= max_len):
                if dp[i] > max_total:
                    max_total = dp[i]
                    best_end = i
    else:
        # Streaming: Select best cut endpoint within lookahead horizon
        for i in range(1, num_nodes):
            if dp[i] != float('-inf') and nodes[i][0] <= horizon_limit:
                if dp[i] > max_total:
                    max_total = dp[i]
                    best_end = i

    if best_end <= 0:
        return []

    # Reconstruct cut sequence by backtracking through parent pointers
    cuts = []
    curr = best_end
    while curr > 0:
        cuts.append(nodes[curr])
        curr = parent[curr]
    cuts.reverse()

    return cuts