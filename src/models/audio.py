import re
import json
import shlex
import subprocess

# Experimental audio library
# Aims to pass through to ffmpeg and test for validity, but includes manual enhancements.

# Somewhat aggressive fallback bit rates for opus
OPUS_TARGET_LADDER = {
    1: "48k",
    2: "96k",
    6: "192k",
    8: "256k",
    "fallback": lambda channels: f"{channels * 32}k"
}

def probe_audio_streams(input_path):
    """Probes channels and channel_layout for audio streams."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index,channels,channel_layout",
        "-of", "json", input_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout).get("streams", [])
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

def get_opus_target_bitrate(channels):
    if channels in OPUS_TARGET_LADDER:
        return OPUS_TARGET_LADDER[channels]
    fallback = OPUS_TARGET_LADDER.get("fallback")
    return fallback(channels) if callable(fallback) else "96k"

def parse_user_args(user_tokens):
    user_maps = []
    user_codecs = {}
    user_bitrates = {}
    user_channel_counts = {}  # Tracks -ac or -ac:a:x
    has_custom_filters = False  # Tracks if user provides -af or -filter:a

    i = 0
    while i < len(user_tokens):
        token = user_tokens[i]

        if token in ["-map", "--map"] and i + 1 < len(user_tokens):
            user_maps.append(user_tokens[i + 1])
            i += 2
        elif token.startswith(("-c:a", "-codec:a")):
            specifier = token.split(":", 1)[1] if ":" in token else "a"
            if i + 1 < len(user_tokens):
                user_codecs[specifier] = user_tokens[i + 1]
                i += 2
            else:
                i += 1
        elif token.startswith(("-b:a", "-b:a:")):
            specifier = token.split(":", 1)[1] if ":" in token else "a"
            if i + 1 < len(user_tokens):
                user_bitrates[specifier] = user_tokens[i + 1]
                i += 2
            else:
                i += 1
        elif token.startswith(("-ac", "-ac:a")):
            specifier = token.split(":", 1)[1] if ":" in token else "a"
            if i + 1 < len(user_tokens):
                user_channel_counts[specifier] = int(user_tokens[i + 1])
                i += 2
            else:
                i += 1
        elif token in ["-af", "-filter:a"] or token.startswith("-filter:a:"):
            has_custom_filters = True
            i += 2 if i + 1 < len(user_tokens) else 1
        else:
            i += 1

    return user_maps, user_codecs, user_bitrates, user_channel_counts, has_custom_filters

def build_audio_args(input_path, user_arg_str=""):
    if not user_arg_str:
        user_arg_str = ""
    user_tokens = shlex.split(user_arg_str)
    user_maps, user_codecs, user_bitrates, user_channels, has_custom_filters = parse_user_args(user_tokens)

    audio_streams = probe_audio_streams(input_path)
    generated_args = []

    # 1. Resolve Mappings
    if not user_maps:
        if audio_streams:
            best_idx = max(range(len(audio_streams)), key=lambda idx: audio_streams[idx].get("channels", 0))
            generated_args.extend(["-map", f"0:a:{best_idx}"])
            mapped_streams = [(0, audio_streams[best_idx])]
        else:
            mapped_streams = []
    else:
        mapped_streams = [(i, stream) for i, stream in enumerate(audio_streams)]

    # 2. Process mapped streams
    for out_idx, (stream_idx, stream_info) in enumerate(mapped_streams):
        spec = f"a:{out_idx}"

        # Determine active channel count (check if user forced -ac)
        forced_channels = user_channels.get(spec) or user_channels.get("a")
        probed_channels = stream_info.get("channels", 2)
        effective_channels = forced_channels if forced_channels else probed_channels

        # Codec & Bitrate definitions
        explicit_codec = user_codecs.get(spec) or user_codecs.get("a")
        explicit_bitrate = user_bitrates.get(spec) or user_bitrates.get("a")

        if not explicit_codec:
            # Default passthrough
            generated_args.extend([f"-c:{spec}", "copy"])
        else:
            is_opus = "opus" in explicit_codec.lower()

            if is_opus:
                # Target bitrate from ladder
                if not explicit_bitrate:
                    target_bitrate = get_opus_target_bitrate(effective_channels)
                    generated_args.extend([f"-b:{spec}", target_bitrate])

                # ONLY apply surround rules if the user HAS NOT overridden channel count
                if not forced_channels:
                    # libopus requires mapping_family 1 for surround sound bit rate allocation, for some reason
                    if effective_channels > 2:
                        generated_args.extend([f"-mapping_family:{spec}", "1"])

                    # Prevent errors with 5.1 side
                    layout = stream_info.get("channel_layout", "")
                    if effective_channels == 6 and "side" in layout and not has_custom_filters:
                        generated_args.extend([f"-filter:{spec}", "aformat=channel_layouts=5.1"])

    # 3. Append original user tokens
    generated_args.extend(user_tokens)
    return generated_args

def test_audio_mappings(generated_args, input_file):
    # Construct full test command
    cmd = ["ffmpeg", "-i", input_file, "-y"] + generated_args + ["-t", "1", "-f", "null", "-"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        stderr_output = result.stderr
    except subprocess.CalledProcessError as e:
        # Return error details if FFmpeg fails
        error_lines = [
            line.strip()
            for line in e.stderr.splitlines()
            if "Error" in line or "Invalid" in line
        ]
        err_msg = error_lines[-1] if error_lines else "FFmpeg execution failed."
        return False, [f"Error: {err_msg}"]
    except FileNotFoundError:
        return False, ["Error: ffmpeg executable not found."]

    # Parse stderr for output audio stream declarations
    formatted_mappings = parse_output_audio_mappings(stderr_output)
    return True, formatted_mappings

def parse_output_audio_mappings(stderr_text):
    lines = stderr_text.splitlines()

    # 1. Parse source codec per output stream index from "Stream mapping:" section
    # Target line: "  Stream #0:1 -> #0:0 (truehd (native) -> opus (libopus))"
    source_codecs = {}
    mapping_pattern = re.compile(
        r"^\s*Stream\s+#\d+:\d+\s+->\s+#0:(\d+)\s+\(([^()\s]+)"
    )

    in_mapping_section = False
    for line in lines:
        if "Stream mapping:" in line:
            in_mapping_section = True
            continue

        if in_mapping_section:
            match = mapping_pattern.match(line)
            if match:
                out_idx = match.group(1)
                src_codec = match.group(2)
                source_codecs[out_idx] = src_codec
            elif line.strip() and not line.startswith(" "):
                in_mapping_section = False

    # 2. Parse final specs from "Output #0" stream declarations
    # Target line: "  Stream #0:0(eng): Audio: opus, 48000 Hz, 7.1, flt, 256 kb/s"
    output_pattern = re.compile(
        r"^\s*Stream\s+#\d+:(\d+)(?:\(([^)]+)\))?:\s+Audio:\s+(.+)$"
    )

    mappings = []
    in_output_section = False

    for line in lines:
        if "Output #0" in line:
            in_output_section = True
            continue

        if in_output_section:
            match = output_pattern.match(line)
            if match:
                out_idx = match.group(1)
                lang = match.group(2)
                specs = match.group(3)

                src_codec = source_codecs.get(out_idx, "unknown")
                lang_str = f" [{lang}]" if lang else ""

                # Format copying differently
                if (src_codec == "copy"):
                    clean_entry = (
                        f"Audio #{out_idx}{lang_str} ({src_codec}) {specs}"
                    )
                else:
                    clean_entry = (
                        f"Audio #{out_idx}{lang_str} {src_codec} -> {specs}"
                    )
                mappings.append(clean_entry)

    return mappings

class AudioMappings:
    def __init__(self, source, audio_args):
        processed_args = build_audio_args(source, audio_args)
        success, formatted_mappings = test_audio_mappings(processed_args, source)
        if not success:
            # Throw Exception here soon lol
            pass
        self.audio_args = processed_args
        self.formatted_mappings = formatted_mappings