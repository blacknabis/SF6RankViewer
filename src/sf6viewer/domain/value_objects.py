"""Domain value objects."""

from dataclasses import dataclass

from sf6viewer.domain.errors import error_from_code


@dataclass(frozen=True, slots=True)
class UserCode:
    """A validated ten-digit user code."""

    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or len(self.value) != 10
            or not self.value.isascii()
            or not self.value.isdecimal()
        ):
            raise error_from_code("VALIDATION.USER_CODE")

    @classmethod
    def parse(cls, raw: object) -> "UserCode":
        """Parse a raw user code."""
        if not isinstance(raw, str):
            raise error_from_code("VALIDATION.USER_CODE")

        value = raw.strip()
        return cls(value)
