from pydantic import BaseModel, EmailStr, Field, field_validator


class FeedbackIn(BaseModel):
    message: str = Field(..., min_length=10, max_length=2000)
    email: EmailStr | None = Field(None)

    @field_validator("email", mode="before")
    @classmethod
    def empty_string_to_none(cls, v: str | None) -> str | None:
        """Convert empty string to None for optional email."""
        if v == "":
            return None
        return v


class FeedbackOut(BaseModel):
    success: bool
    message: str
