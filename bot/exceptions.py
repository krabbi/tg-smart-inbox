class ClassificationError(Exception):
    """Raised when Claude API fails to classify a message."""


class DriveUploadError(Exception):
    """Raised when Google Drive upload fails."""


class ReminderParseError(Exception):
    """Raised when reminder time cannot be parsed from user input."""


class ScrapingError(Exception):
    """Raised when a URL cannot be fetched or parsed."""


class TimeParseError(Exception):
    """Raised when a natural language time expression cannot be parsed."""
