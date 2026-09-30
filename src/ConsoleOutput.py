import sys
import time

class ConsoleOutput:
    def __init__(self, resolution, hdr, length, source_fps):
        self.resolution = resolution
        self.hdr = hdr
        self.length = length
        self.source_fps = source_fps
        self.messages = []
        self.printed_messages = []

    def print(self, msg):
        """Adds a message to be printed above the progress bar."""
        self.messages.append(msg)

    def update_display(self, worker_threads, scene_manager, passed_time, total_processed_length, progress, fps, eta):
        # Move up to the progress bar area
        sys.stdout.write("\033[2F")
        
        # Clear and write progress bar
        sys.stdout.write(f"\033[KScenes {sum(1 for s in scene_manager.scenes if s.done_processing)}/{len(scene_manager.scenes)} Workers {sum(1 for t in worker_threads if t.is_alive())} ")
        sys.stdout.write(f"\033[K{self.resolution[0]}x{self.resolution[1]} {'HDR' if self.hdr else 'SDR'}\n")
        
        bar_width = 60
        filled = int(progress / 1.0 * bar_width)
        bar = "#" * filled + ">" + "-" * (bar_width - filled - 1)
        line = f"[{passed_time}] [{bar[:bar_width]}] {round(progress*100,1)}% {round(fps,1)} fps, eta {eta}"
        sys.stdout.write(f"\033[K{line}\n")
        sys.stdout.flush()

        # Print new messages above the progress bar
        for msg in self.messages:
            if msg not in self.printed_messages:
                sys.stdout.write("\033[A") # Move up
                sys.stdout.write(f"{msg}\n")
                self.printed_messages.append(msg)
