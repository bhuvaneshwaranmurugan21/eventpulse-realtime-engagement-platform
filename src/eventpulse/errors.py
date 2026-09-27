"""Typed EventPulse failure classes."""


class EventPulseError(Exception):
    """Base EventPulse failure."""


class RetryableDependencyError(EventPulseError):
    """A dependency failure for which the Kinesis record must be retried."""


class InvariantViolation(EventPulseError):
    """An internal invariant failure that cannot be acknowledged."""


class DuplicateKeyError(ValueError):
    """A JSON object contained the same key more than once."""
