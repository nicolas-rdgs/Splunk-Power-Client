class InstanceNotFound(Exception):
    def __init__(self, instance_name: str):
        self.instance_name = instance_name

    def __str__(self):
        return f"Instance '{self.instance_name}' not found"
