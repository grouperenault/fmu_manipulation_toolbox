"""Error of the container builder."""

class FMUContainerError(Exception):
    """Exception raised for errors during FMU Container operations.

    Attributes:
        reason (str): Human-readable description of the error.
    """

    def __init__(self, reason: str):
        self.reason = reason

    def __repr__(self):
        return f"{self.reason}"
