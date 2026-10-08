import argparse
from pathlib import Path
import re

from src.models.audio import AudioMappings
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

    parser.add_argument("-i", help="Path to the input file.", type=valid_file_type, required=True, metavar="FILE")
    parser.add_argument("-o", help="Path to the output file.", type=Path, required=True, metavar="FILE")
    parser.add_argument("-w", type=int, help="Set the number of workers.", metavar="N", default=1)
    parser.add_argument("--low_power", dest="low_power", action="store_true", default=False, help="Enable low power mode (macOS only).")
    parser.add_argument("--disable-ten-bit", dest="ten_bit", action="store_false", default=True, help="Disable 10 bit encoding")
    parser.add_argument("--disable-hwaccel", dest="hwaccel", action="store_false", default=True, help="Disable hardware accelerated decoding")
    parser.add_argument("--autocrop", dest="autocrop", action="store_true", default=False, help="Enable automatic cropping.")
    parser.add_argument("--res", type=resolution_type, help="Set resolution limit (e.g. 1920x1080).", metavar="WxH")
    parser.add_argument("-v", "--video-params", type=str, help="Parameters for chosen video encoder. Defaults vary by encoder.")
    parser.add_argument("-a", "--audio-params", type=str, help="Parameters for audio mapping and encoding.")

    return parser.parse_args()

class Config:
    def __init__(self, args):
        self.input_file = args.i
        self.output_file = args.o
        self.workers = max(args.w, 1)
        self.hwaccel = args.hwaccel
        self.low_power = args.low_power
        self.ten_bit = args.ten_bit

        self.audio_mappings = AudioMappings(self.input_file, args.audio_params)
        self.video_attributes = VideoAttributes(self.input_file, args.autocrop, args.res)
        self.video_encoding = SvtAv1(args.video_params)