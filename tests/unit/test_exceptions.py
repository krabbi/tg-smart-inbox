from bot.exceptions import ClassificationError, DriveUploadError, ReminderParseError


def test_classification_error_is_exception() -> None:
    err = ClassificationError("Claude API unavailable")
    assert isinstance(err, Exception)
    assert str(err) == "Claude API unavailable"


def test_drive_upload_error_is_exception() -> None:
    err = DriveUploadError("upload failed")
    assert isinstance(err, Exception)
    assert str(err) == "upload failed"


def test_reminder_parse_error_is_exception() -> None:
    err = ReminderParseError("cannot parse time")
    assert isinstance(err, Exception)
    assert str(err) == "cannot parse time"


def test_exceptions_are_catchable_as_base_exception() -> None:
    for exc_class in (ClassificationError, DriveUploadError, ReminderParseError):
        try:
            raise exc_class("test")
        except Exception as e:
            assert isinstance(e, exc_class)
