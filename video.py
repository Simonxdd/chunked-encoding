from pathlib import Path
import concurrent.futures
import subprocess
import json
import re
import sys


def get_crop_backup(source):
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-skip_frame", "nokey", "-i", source, "-nostdin",
                "-vf", "cropdetect=64:2:0",
                "-t", "00:10:00",
                "-f", "null", "/dev/null"
            ],
            stderr=subprocess.PIPE,
            errors="replace",
            text=True,
            check=True
        )
        output = result.stderr
        crop_lines = [line for line in output.splitlines() if 'crop=' in line]
        if crop_lines:
            last_line = crop_lines[-1]
            match = re.search(r'crop=(\d+:\d+:\d+:\d+)', last_line)
            if match:
                crop = match.group(0)
                return crop
        return None
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return None

def get_crop(source):
    try:
        duration_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", source
        ]
        duration_res = subprocess.run(duration_cmd, capture_output=True, text=True, check=True)
        total_duration = float(duration_res.stdout.strip())

        start_buffer, end_buffer = total_duration * 0.05, total_duration * 0.95
        scan_duration = end_buffer - start_buffer
        num_points, frames_per_point = 6, 8
        interval = scan_duration / (num_points + 1)

        def probe_point(source, timestamp, frames_per_point):
            result = subprocess.run([
                "ffmpeg", "-ss", str(timestamp), "-skip_frame", "nokey", "-i", source, "-nostdin",
                "-frames:v", str(frames_per_point), "-vf", "cropdetect=64:2:0", "-f", "null", "-"
            ], stderr=subprocess.PIPE,
                errors="replace",
                text=True,
                check=True
            )
            output = result.stderr
            matches = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', result.stderr)
            if matches:
                w, h, x, y = map(int, matches[-1])
                return ({'w': w, 'h': h, 'x': x, 'y': y, 'area': w * h})

        futures = []
        crop_candidates = []

        with concurrent.futures.ThreadPoolExecutor() as executor:
            for i in range(1, num_points + 1):
                timestamp = start_buffer + (i * interval)
                future = executor.submit(probe_point, source, timestamp, frames_per_point)
                futures.append(future)

        for future in futures:
            crop_candidates.append(future.result())

        if not crop_candidates:
            return get_crop(source)

        best_crop = max(crop_candidates, key=lambda x: x['area'])

        final_crop_str = f"crop={best_crop['w']}:{best_crop['h']}:{best_crop['x']}:{best_crop['y']}"
        return final_crop_str
    except Exception as e:
        return get_crop_backup(source)

def get_output_resolution(source, crop, limit):
    if crop:
        crop_with_space = crop.replace(':', ' ').replace('=', ' ')
        parts = crop_with_space.split()
        x, y = int(parts[1]), int(parts[2])
    else:
        cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-select_streams", "v:0", "-show_entries",
                                  "stream=width,height", source]
        output = json.loads(subprocess.check_output(cmd).decode('utf-8'))
        x = int(output["streams"][0]["width"])
        y = int(output["streams"][0]["height"])

    if limit:
        limit_x, limit_y = limit
        x_ratio = limit_x / x
        y_ratio = limit_y / y

        factor = min(x_ratio, y_ratio)

        if factor < 1:
            x = int(round(x * factor))
            y = int(round(y * factor))
    return x, y

def get_characteristics(source):
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-select_streams", "v:0",
           "-show_entries","format=duration:stream=r_frame_rate", source]
    output = json.loads(subprocess.check_output(cmd).decode('utf-8'))
    return output


def get_video_start(source):
    cmd = [
        "ffmpeg", "-i", source, "-nostdin", "-hide_banner", "-nostats",
        "-filter_complex",
        "[0:v]trim=duration=7,blackdetect=d=0.05:pic_th=0.999:pix_th=0.10[v];"
        "[0:a]atrim=duration=15,silencedetect=n=-50dB:d=0.05[a]",
        "-map", "[v]", "-map", "[a]", "-t", "15",
        "-f", "null", "-"
    ]

    try:
        output = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, check=True).stderr
        black_end = 0.0
        silence_end = 0.0

        # Regex for Blackdetect
        black_match = re.search(r'black_start:([0-9.]+).*?black_end:([0-9.]+)', output)
        if black_match and float(black_match.group(1)) < 0.1:
            black_end = float(black_match.group(2))

        # Regex for Silencedetect
        # Finding the first silence_end that corresponds to a start near 0
        silence_matches = re.finditer(r'silence_start: ([-0-9.]+).*?silence_end: ([-0-9.]+)', output, re.DOTALL)
        for match in silence_matches:
            if float(match.group(1)) < 0.1:
                silence_end = float(match.group(2))
                break

        result = min(black_end, silence_end)
        return result

    except Exception as e:
        return 0.0

def get_hdr(source):
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=color_transfer",
        "-of", "default=noprint_wrappers=1", source
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        if re.search(r'color_transfer=smpte2084', output):
            return True
        else:
            return False
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error running ffprobe to check eotf: {e}", file=sys.stderr)