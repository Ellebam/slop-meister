"""One error type for the whole product. Commands raise it, the CLI prints it and exits."""

EXIT_FAILURE = 1
EXIT_USAGE = 2


class SlopmeisterError(Exception):
    """A reported failure with a message for the operator and a process exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_FAILURE) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class UsageError(SlopmeisterError):
    """Wrong arguments or a missing prerequisite the caller controls."""

    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_USAGE)
