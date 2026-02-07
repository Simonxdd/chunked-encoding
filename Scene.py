class Scene:
    def __init__(self, start):
        self.start = start
        self.end = None
        self.is_processing = False

    def end_scene(self, end):
        self.end = end

    def is_complete(self):
        return self.end is not None

    def get_length(self):
        if self.end is not None:
            return self.end - self.start
        else:
            return float("inf")

    def update_processing_state(self, arg):
        self.is_processing = arg

    def get_processing_state(self):
        return self.is_processing