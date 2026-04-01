"""Infographic module for composing narrative sports graphics."""


class Infographic:
    """Generates infographic assets tailored for basketball story posts."""

    def __init__(self) -> None:
        self.layout = "vertical"

    def main(self, narrative_data: dict) -> str:
        raise NotImplementedError("Infographic generation is not implemented yet.")
