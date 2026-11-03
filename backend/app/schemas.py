from typing import Literal
from pydantic import BaseModel, Field, field_validator

class CreateRoom(BaseModel):
    name: str = Field(min_length=1, max_length=24)
    game_mode: Literal["CLASSIC", "FULL_EXPERIENCE_8"] = "CLASSIC"

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value

class JoinRoom(CreateRoom):
    code: str = Field(min_length=6, max_length=8)

    @field_validator("code")
    @classmethod
    def clean_code(cls, value):
        return value.strip().upper()

class ReadyRequest(BaseModel):
    ready: bool

class RoundDurationRequest(BaseModel):
    duration_seconds: Literal[30, 60, 90, 120]

class DraftRequest(BaseModel):
    subject_id: str
    text: str = Field(max_length=250)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Description cannot be blank")
        return value

class SubmitDescriptions(BaseModel):
    descriptions: dict[str, str]

class GuessRequest(BaseModel):
    description_id: str
    author_guess_id: str | None = None
    subject_guess_id: str | None = None

class ContinueRequest(BaseModel):
    expected_version: int | None = None

class TiebreakerDescriptions(BaseModel):
    descriptions: dict[str, str]

    @field_validator("descriptions")
    @classmethod
    def clean_text(cls, value):
        cleaned = {subject_id: text.strip() for subject_id, text in value.items()}
        if any(not text or len(text) > 250 for text in cleaned.values()):
            raise ValueError("Each description must contain 1 to 250 characters")
        return cleaned

class TiebreakerGuessRequest(BaseModel):
    prompt_id: str
    author_guess_id: str
