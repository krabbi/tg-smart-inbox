class ClassificationError(Exception):
    """Raised when Claude API fails to classify a message."""


class DriveUploadError(Exception):
    """Raised when Google Drive upload fails."""


class ReminderParseError(Exception):
    """Raised when reminder time cannot be parsed from user input."""
