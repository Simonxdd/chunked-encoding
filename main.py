import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import re
import shutil
from EncodingProcess import EncodingProcess

import time

import video


def main():
    parser = argparse.ArgumentParser(description='test description #1')
    # input/output
    parser.add_argument("-i", help="Path to the input file.", type=valid_path, required=True, metavar="FILE")
    parser.add_argument("-o", help="Path to the output file.", type=Path, required=True, metavar="FILE")
    parser.add_argument("-w", type=int, help="Set the number of workers. Default is 4. not working yet.", metavar="N")
    # autocrop, resolution limit
    parser.add_argument("--autocrop", action=argparse.BooleanOptionalAction, default=True,
                        help="Enable or disable automatic cropping. not working yet.")
    parser.add_argument("--findstart", action=argparse.BooleanOptionalAction, default=True,
                        help="Automatically find the start of the video using audio and video analysis.")
    parser.add_argument("--res", type=resolution_type,
                        help="Set resolution limit (e.g. 1920x1080). Downscales to longest axis. not working yet.", metavar="WxH")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("no ffmpeg version was found on this system.")
    with ThreadPoolExecutor() as executor:
        future_crop = executor.submit(video.get_crop, args.i) if args.autocrop else None
        future_start = executor.submit(video.get_video_start, args.i) if args.findstart else None
        future_hdr = executor.submit(video.get_hdr, args.i)

    crop = future_crop.result() if future_crop else None
    start = future_start.result() if future_start else 0.0
    hdr = future_hdr.result()
    video_json = video.get_characteristics(args.i)
    length = float(video_json["format"]["duration"])
    fps = video_json["streams"][0]["r_frame_rate"]
    if "/" in fps:
        num, den = fps.split("/")
        fps = float(num) / float(den)
    else:
        fps = float(fps)

    resolution = video.get_output_resolution(args.i, crop, args.res)
    process = EncodingProcess(args.i, args.o, crop, resolution, start, length, fps, hdr)
    process.start()


def valid_path(path_str):
    p = Path(path_str)
    if not p.exists():
        raise argparse.ArgumentTypeError(f"Path does not exist: {path_str}")
    return p.as_posix()

def resolution_type(string):
    if not re.match(r"^\d+x\d+$", string):
        raise argparse.ArgumentTypeError(f"Resolution '{string}' must be in WIDTHxHEIGHT format (e.g., 1920x1080)")
    width, height = map(int, string.split('x'))
    return width, height

if __name__ == '__main__':
    main()