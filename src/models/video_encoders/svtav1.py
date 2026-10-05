
class SvtAv1:
    """
    Handles video encoding settings for SVT-AV1, including psychovisual enhancements
    merged from SVT-AV1-HDR.
    """
    NAME = "svt-av1"

    def __init__(self, args_str: str = ""):
        # Default params, including base psychovisual params (merged from SVT-AV1-HDR)
        self.params = {
            "preset": 4,
            "crf": 35,
            "ac-bias": 1.0,
            "sharpness": 1,
            "tf-strength": 1,
            # "kf-tf-strength": 1, Currently missing in mainline
            "enable-variance-boost": 1,
            # "noise-norm-strength": 1, Currently missing in mainline
            #"hbd-mds": 1, # Setting this to 1 causes segfaults on my Mac.
            # "sharp-tx": 1, Currently missing in mainline
            "enable-qm": 1,
            "qm-min": 5,
            "qm-max": 10,
            "keyint": 300
            # "noise-norm-strength": 1 Currently missing in mainline
        }
        self._parse_args(args_str)

    def _parse_args(self, args_str: str):
        if not args_str:
            return
        if "reset-all" in args_str:
            self.params = {}
        # FFmpeg-style formatting: "key=value:key=value"
        if "=" in args_str and "--" not in args_str:
            for part in args_str.split(":"):
                if "=" in part:
                    key, val = part.split("=", 1)
                    self.params[key.strip()] = val.strip()
        # CLI formatting: "--key value --key value"
        else:
            parts = args_str.split()
            i = 0
            while i < len(parts):
                part = parts[i]
                if part.startswith("-"):
                    key = part.lstrip("-")
                    # Handle space-separated: --key value
                    if "=" not in key:
                        if i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                            self.params[key] = parts[i + 1]
                            i += 1
                    # Handle equals-separated: --key=value
                    else:
                        k, v = key.split("=", 1)
                        self.params[k] = v
                i += 1


    def get_ffmpeg_args(self) -> list:
        args = ["-c:v", "libsvtav1"]
        if self.params:
            svt_params = ":".join(f"{key}={val}" for key, val in self.params.items())
            args.extend(["-svtav1-params", svt_params])
        return args

    def get_raw_args(self) -> str:
        if self.params:
            return " ".join(f"{key}={val}" for key, val in self.params.items())
        return "(None)"

    def warning_filter(self, string):
        if "Error parsing option" in string:
            return True
        return False

    def __repr__(self):
        return f"<SvtAv1(params={self.params})>"
