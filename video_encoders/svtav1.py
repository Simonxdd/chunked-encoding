from typing import Dict, Any, Union, Optional

def _validate_crf(crf: Union[int, float]) -> Union[int, float]:
    try:
        crf_val = float(crf)
    except (ValueError, TypeError):
        raise ValueError(f"CRF must be a number. Received: {crf}")

    if not (1.0 <= crf_val <= 70.0):
        raise ValueError(f"CRF must be between 1 and 70. Received: {crf_val}")

    if not (crf_val * 4 == int(crf_val * 4)):
        raise ValueError(f"CRF must be a multiple of 0.25. Received: {crf_val}")

    return crf_val

def _validate_preset(preset: int) -> int:
    if not (-1 <= preset <= 13):
        raise ValueError(f"Preset must be between -1 and 13. Received: {preset}")
    return preset

class SvtAv1:
    """
    Handles video encoding settings for SVT-AV1, including psychovisual enhancements
    merged from SVT-AV1-HDR.
    """
    NAME = "svt-av1"
    DEFAULT_CRF = 35
    DEFAULT_PRESET = 5

    def __init__(self, crf: Union[int, float] = None, preset: int = None, args_str: str = None):
        # Base psychovisual parameters (merged from SVT-AV1-HDR)
        self.params = {
            "ac-bias": 1.0,
            "sharpness": 1,
            "tf-strength": 1,
            # "kf-tf-strength": 1, Currently missing in mainline
            "enable-variance-boost": 1,
            # "noise-norm-strength": 1, Currently missing in mainline
            "hbd-mds": -1, # Setting this to 1 causes segfaults on my Mac.
            # "sharp-tx": 1, Currently missing in mainline
            "enable-qm": 1,
            "qm-min": 5,
            "qm-max": 10,
            # "noise-norm-strength": 1, Currently missing in mainline
        }

        # Set crf and preset from args or defaults
        self.crf = _validate_crf(crf if crf is not None else self.DEFAULT_CRF)
        self.preset = _validate_preset(preset if preset is not None else self.DEFAULT_PRESET)
        self._parse_args(args_str)

    def _parse_args(self, args_str: str):
        if not args_str:
            return

        parts = []
        if ":" in args_str and "--" not in args_str:
            parts = args_str.split(":")
        else:
            parts = args_str.split()

        for part in parts:
            if "=" in part:
                kv = part.strip("-").split("=")
                if len(kv) == 2:
                    key, val = kv[0], kv[1]
                    if key == "crf":
                        self.crf = _validate_crf(val)
                    elif key == "preset":
                        self.preset = _validate_preset(val)
                    else:
                        self.params[key] = val

    def get_ffmpeg_args(self) -> list:
        args = ["-c:v", "libsvtav1"]
        args.extend(["-preset", str(self.preset)])
        args.extend(["-crf", str(self.crf)])
        if self.params:
            svt_params = ":".join(f"{key}={val}" for key, val in self.params.items())
            args.extend(["-svtav1-params", svt_params])
        return args

    def warning_filter(self, string):
        if "Error parsing option" in string:
            return True
        return False

    def __repr__(self):
        return f"<SvtAv1(crf={self.crf}, preset={self.preset}, params={self.params})>"
