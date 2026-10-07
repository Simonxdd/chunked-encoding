import json
from pathlib import Path
from time import *
import threading
import os

filename = "scenes.json"

class SceneManager:
    def __init__(self, temp_location: Path, content_start_time):
        self.temp_location = temp_location
        self.scenes = []
        self.start_timestamp = time()
        self.most_recent_timestamp = None
        self.finished_length = 0.0
        self.lock = threading.Condition()
        self.scd_finished = False

        if os.path.exists(self.temp_location / filename):
            self.load_scenes()
        else:
            self.scenes.append(Scene(content_start_time))

    def add_scene(self, timestamp):
        with self.lock:
            idx = len(self.scenes) - 1
            self.scenes[idx].end_scene(timestamp)
            self.scenes.append(Scene(timestamp))
            if not self.scenes[idx].get_length() > 1.0:
                self.scenes[idx].end_scene(None)
                self.scenes.pop(idx + 1)
            self.lock.notify_all()

    def finish_last_scene(self, timestamp):
        with self.lock:
            self.scenes[len(self.scenes)-1].end_scene(timestamp)
            self.scd_finished = True
            self.lock.notify_all()

    def request_scene(self):
        with self.lock:
            while True:
                available_scenes = [s for s in self.scenes if s.is_complete()
                                    and not s.is_processing and not s.done_processing]
                if available_scenes:
                    scene = available_scenes[0]
                    scene.is_processing = True
                    return scene, self.scenes.index(scene)
                if self.scd_finished:
                    return None, None
                self.lock.wait()

    def release_scene(self, scene):
        with self.lock:
            scene.is_processing = False
            self.lock.notify_all()

    def unprocessed_scenes(self):
        return any(not scene.done_processing for scene in self.scenes)

    def scene_finished(self, scene):
        with self.lock:
            scene.done_processing = True
            scene.is_processing = False
            self.most_recent_timestamp = time()
            self.finished_length += scene.get_length()
            if self.scd_finished:
                self.save_scenes()

    def save_scenes(self):
        serialized = [s.serialize() for s in self.scenes]
        with open(self.temp_location / filename, "w") as f:
            json.dump(serialized, f, indent=4)


    def load_scenes(self):
        with open(self.temp_location / filename, "r", encoding="utf-8") as f:
            serialized = json.load(f)
            self.scenes = [Scene.deserialize(item) for item in serialized]
            self.scd_finished = True
            for scene in self.scenes:
                if not scene.done_processing and scene.is_processing:
                    scene.is_processing = False

    def clean_up(self):
        os.remove(self.temp_location / filename)

class Scene:
    def __init__(self, start):
        self.start = start
        self.end = None
        self.is_processing = False
        self.done_processing = False
        self.error_count = 0

    def end_scene(self, end):
        self.end = end

    def is_complete(self):
        return self.end is not None

    def get_length(self):
        if self.end is not None:
            return self.end - self.start
        else:
            return float("inf")

    def serialize(self):
        return self.__dict__

    @classmethod
    def deserialize(cls, data):
        start_value = data.pop('start')
        instance = cls(start_value)
        instance.__dict__.update(data)
        return instance