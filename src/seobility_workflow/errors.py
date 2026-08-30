"""Workflow-specific exceptions."""


class WorkflowError(Exception):
    """Base class for expected workflow failures."""


class InvalidTransitionError(WorkflowError):
    """Raised when a run attempts an invalid state transition."""


class ArtifactError(WorkflowError):
    """Raised when an artifact is absent, unsafe, or inconsistent."""


class ValidationError(WorkflowError):
    """Raised when one or more deterministic validations fail."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))
