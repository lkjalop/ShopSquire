"""Runtime compatibility for the supported Python 3.10+ matrix."""
try:
    from enum import StrEnum
except ImportError:  # Python 3.10; equivalent string conversion and auto() semantics.
    from enum import Enum

    class StrEnum(str, Enum):
        __str__ = str.__str__
        __format__ = str.__format__

        @staticmethod
        def _generate_next_value_(name, start, count, last_values):
            return name.lower()
