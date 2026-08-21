"""Domain exceptions mapped to the unified ErrorResponse contract."""


class AppError(Exception):
    """Base error. Subclasses set HTTP status and ErrorResponse fields."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    retryable: bool = False
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class CreditsExhaustedError(AppError):
    status_code = 503
    error_code = "CREDITS_EXHAUSTED"
    retryable = False
    default_message = (
        "AI service temporarily unavailable. Please recharge the OpenRouter account."
    )


class LLMTimeoutError(AppError):
    status_code = 503
    error_code = "LLM_TIMEOUT"
    retryable = True
    default_message = "The AI service timed out. Please try again."


class LLMRateLimitedError(AppError):
    status_code = 503
    error_code = "LLM_RATE_LIMITED"
    retryable = True
    default_message = "The AI service is rate limited. Please try again shortly."


class SessionNotFoundError(AppError):
    status_code = 404
    error_code = "SESSION_NOT_FOUND"
    retryable = False
    default_message = "Session not found."


class SessionExpiredError(AppError):
    status_code = 410
    error_code = "SESSION_EXPIRED"
    retryable = False
    default_message = "Session expired. Please start a new conversation."


class SessionActiveError(AppError):
    status_code = 409
    error_code = "SESSION_ACTIVE"
    retryable = False
    default_message = "Session is still active. End the session to generate analytics."


class BookingFailedError(AppError):
    status_code = 409
    error_code = "BOOKING_FAILED"
    retryable = True
    default_message = "Booking could not be completed. Please try another slot."


class RateLimitExceededError(AppError):
    status_code = 429
    error_code = "RATE_LIMITED"
    retryable = True
    default_message = "Too many messages. Please wait a moment and try again."
