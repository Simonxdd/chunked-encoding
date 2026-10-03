import argparse
from pathlib import Path
import re

from src.models.video_encoders.svtav1 import SvtAv1
from src.models.video import VideoAttributes

def valid_file_type(path_str):
    p = Path(path_str)
    if not p.exists():
        raise argparse.ArgumentTypeError(f"Path does not exist: {path_str}")
    return p.as_posix()

def resolution_type(string):
    if not re.match(r"^\d+x\d+$", string):
        raise argparse.ArgumentTypeError(f"Resolution '{string}' must be in WIDTHxHEIGHT format (e.g., 1920x1080)")
    width, height = map(int, string.split('x'))
    return width, height

def parse_cli_args():
    parser = argparse.ArgumentParser(description="Chunked Encoding indev")
    arg_bool = argparse.BooleanOptionalAction

    parser.add_argument("-i", help="Path to the input file.", type=valid_file_type, required=True, metavar="FILE")
    parser.add_argument("-o", help="Path to the output file.", type=Path, required=True, metavar="FILE")
    parser.add_argument("-w", type=int, help="Set the number of workers.", metavar="N", default=1)
    parser.add_argument("--low_power", action=arg_bool, default=False, help="Enable low power mode (macOS only).")
    parser.add_argument("--ten_bit", action=arg_bool, default=True, help="Enable 10 bit encoding. On by default.")
    parser.add_argument("--hwaccel", action=arg_bool, default=True, help="Enable hardware accelerated decoding. On by default.")
    parser.add_argument("--autocrop", action=arg_bool, default=False, help="Enable or disable automatic cropping.")
    parser.add_argument("--res", type=resolution_type, help="Set resolution limit (e.g. 1920x1080).", metavar="WxH")
    parser.add_argument("-v", "--video-params", type=str, help="Parameters for chosen video encoder. Defaults vary by encoder.")

    return parser.parse_args()

class Config:
    def __init__(self, args):
        self.input_file = args.i
        self.output_file = args.o
        self.workers = max(args.w, 1)
        self.hwaccel = args.hwaccel
        self.low_power = args.low_power
        self.ten_bit = args.ten_bit

        self.video_attributes = VideoAttributes(self.input_file, args.autocrop, args.res)
        self.video_encoding = SvtAv1(args.video_params)