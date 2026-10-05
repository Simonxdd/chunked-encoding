import math
import shutil
import sys
import threading
import time
from enum import Enum, auto

from src.models.config import Config
from src.models.scene_management import SceneManager

# TODO: overhaul this mess soon

RESET = "\033[0m"
BOLD_WHITE = "\033[1;97m"
GREEN = "\033[92m"
BLUE = "\033[94m"
GRAY = "\033[90m"
CYAN = "\033[96m"

def format_progress(progress: float) -> str:
    if progress <0.1:
        return str(round(progress * 100, 2))
    if progress > 0.999:
        return "100"
    return str(round(progress * 100, 1))

def format_fps(fps: float) -> str:
    if fps < 1:
        return str(round(fps, 3))
    if fps < 10:
        return str(round(fps, 2))
    return str(round(fps, 1))

class ConsoleOutput:
    class ProcessingState(Enum):
        ANALYZING = auto()
        ENCODING = auto()
        MUXING = auto()

    def __init__(self):
        self.state = self.ProcessingState.ANALYZING
        self.progress = 0.0

        # Persistent area rendering
        self._lines = []
        self._last_printed_count = 0
        self._lock = threading.Lock()
        self.refresh_rate = 1/30

        self.scene_manager = None
        self.config = None
        self.worker_threads = None

    def start(self, scene_manager: SceneManager, config: Config, worker_threads: list[threading.Thread]):
        self.scene_manager = scene_manager
        self.config = config
        self.worker_threads = worker_threads
        self.state = self.ProcessingState.ENCODING

    def stop(self):
        self.state = self.ProcessingState.MUXING
        self.progress = 1.0

    def display_routine(self, stop_event: threading.Event):
        while not stop_event.wait(self.refresh_rate):
            lines = []
            if self.state == self.ProcessingState.ANALYZING:
                lines.append(f"{GRAY}Analyzing...{RESET}")
                timer = f"--:--:--"
                fps = "-.--"
                eta = "--:--:--"
            if self.state == self.ProcessingState.ENCODING:
                for line in self.config.audio_mappings.formatted_mappings:
                    lines.append(f"{GRAY}{line}{RESET}")
                lines.append(f"{GRAY}{self.config.video_encoding.NAME} params: {self.config.video_encoding.get_raw_args()}{RESET}")
                scenes = self.scene_manager.scenes
                video_attributes = self.config.video_attributes
                total_processed_length = sum(s.get_length() for s in scenes if s.done_processing)
                self.progress = min(total_processed_length / video_attributes.length, 1.0)
                if self.scene_manager.most_recent_timestamp:
                    fps = (self.scene_manager.finished_length / (
                            self.scene_manager.most_recent_timestamp - self.scene_manager.start_timestamp)) * video_attributes.source_fps
                    eta = time.strftime('%H:%M:%S', time.gmtime(
                        round((((video_attributes.length - total_processed_length) * video_attributes.source_fps) / fps), 0)))
                    fps = format_fps(fps)
                timer = time.strftime('%H:%M:%S', time.gmtime(time.time() - self.scene_manager.start_timestamp))
                scenes = f"Scenes {sum(1 for s in self.scene_manager.scenes if s.done_processing)}/{sum(1 for s in self.scene_manager.scenes if s.is_complete())}"
                workers = f"Workers {sum(1 for t in self.worker_threads if t.is_alive())}"
                resolution = f"{video_attributes.resolution[0]}x{video_attributes.resolution[1]}"
                hdr = "HDR" if video_attributes.hdr else "SDR"
                lines.append(f"{GREEN}{scenes}{RESET} {BLUE}{workers}{RESET} {GRAY}{resolution} {hdr}{RESET}")
            if self.state == self.ProcessingState.MUXING:
                lines.append(f"{GRAY}Muxing...{RESET}")
                timer = f"--:--:--"
                fps = "-.--"
                eta = "--:--:--"
            line_2_left = f"[{timer}] "
            line_2_right = f" {format_progress(self.progress)}%, {fps} fps, eta {str(eta)} "
            bar_width = shutil.get_terminal_size().columns - len(line_2_left) - len(line_2_right) - 5
            lines.append(line_2_left + self.get_bar(bar_width) + line_2_right)
            self.update_persistent(lines)
        self.clear_persistent()

    def update_persistent(self, lines: list[str]):
        with self._lock:
            self._lines = lines
            current_count = len(self._lines)

            content = "\n".join(f"\033[K{line}" for line in self._lines)

            if self._last_printed_count == 0:
                sys.stdout.write(content + "\n")
            else:
                sys.stdout.write(f"\033[{self._last_printed_count}A\033[J{content}\n")

            sys.stdout.flush()
            self._last_printed_count = current_count

    def clear_persistent(self):
        with self._lock:
            if self._last_printed_count > 0:
                sys.stdout.write(f"\033[{self._last_printed_count}A\033[J")
                sys.stdout.flush()
                self._last_printed_count = 0

    def print(self, message: str):
        with self._lock:
            if self._last_printed_count == 0:
                print(message)
                return

            # 1. Move cursor up
            sys.stdout.write(f"\033[{self._last_printed_count}A\r")

            # 2. Clear from cursor down to the bottom of the screen
            sys.stdout.write("\033[J")

            # 3. Print the regular log message
            print(message)

            # 4. Redraw the existing UI below the log
            content = "\n".join(f"\033[K{line}" for line in self._lines)
            sys.stdout.write(content + "\n")
            sys.stdout.flush()

            self._last_printed_count = len(self._lines)

    # Smooth progress bar written by Gemini
    def get_bar(self, width: int = 30) -> str:
        now = time.perf_counter()

        # Initialize internal tracking state on first run
        if not hasattr(self, '_t_state'):
            self._t_state, self._prev_state, self._trans_start = "spinner", getattr(self, 'state', None), now
            self._spin_start = now
            self.refresh_rate = 1 / 60
            self._last_prog, self._last_prog_time = 0.0, now

        # Detect transition when state changes into ENCODING
        current_state = getattr(self, 'state', None)
        if current_state != self._prev_state:
            if current_state and current_state.name == "ENCODING":
                self._t_state, self._trans_start = "docking", now
                self._dock_pos = (math.sin((now - self._spin_start) * 3.5) + 1) / 2 * (width - 1)
                self._last_prog_time = now  # Reset idle timer so animation isn't throttled
            self._prev_state = current_state

        # Transition animation sequence (~0.2s per phase)
        d = 0.2
        if self._t_state == "docking" and now - self._trans_start >= d:
            self._t_state, self._trans_start = "filling", now
        elif self._t_state == "filling" and now - self._trans_start >= d:
            self._t_state, self._trans_start = "draining", now
        elif self._t_state == "draining" and now - self._trans_start >= d:
            self._t_state = "bar"

        # Normalize progress and handle dynamic refresh rate throttling
        raw_prog = getattr(self, 'progress', 0.0)
        prog = max(0.0, min(1.0, raw_prog / 100.0 if raw_prog > 1.0 else raw_prog))

        if abs(prog - self._last_prog) > 0.001:
            self._last_prog, self._last_prog_time = prog, now
            self.refresh_rate = 1 / 30
        elif self._t_state != "bar":
            self.refresh_rate = 1 / 30
        elif now - self._last_prog_time > 1.0:
            self.refresh_rate = 1 / 4

        target_edge = (width - 1) * prog

        # Render TrueColor cells
        chars = []
        for i in range(width):
            intensity = 0.0
            if self._t_state == "spinner":
                center = (math.sin((now - self._spin_start) * 3.5) + 1) / 2 * (width - 1)
                intensity = math.exp(-((i - center) ** 2) / 8.0)
            elif self._t_state == "docking":
                t = min((now - self._trans_start) / d, 1.0)
                center = self._dock_pos + (width - 1 - self._dock_pos) * ((1 - math.cos(t * math.pi)) / 2)
                intensity = math.exp(-((i - center) ** 2) / 8.0)
            elif self._t_state == "filling":
                t = min((now - self._trans_start) / d, 1.0)
                left = (width - 1) * (1.0 - t)
                intensity = 1.0 if i >= left else math.exp(-((left - i) ** 2) / 8.0)
            elif self._t_state == "draining":
                t = min((now - self._trans_start) / d, 1.0)
                right = (width - 1) - ((width - 1) - target_edge) * t
                intensity = 1.0 if i <= right else math.exp(-((i - right) ** 2) / 8.0)
            else:
                intensity = 1.0 if i <= target_edge else math.exp(-((i - target_edge) ** 2) / 8.0)

            r = 35 - 35 * intensity
            g = 35 + 220 * intensity
            b = 45 + 155 * intensity
            chars.append(f"\033[38;2;{int(r)};{int(g)};{int(b)}m━")

        return "".join(chars) + "\033[0m"

console = ConsoleOutput()