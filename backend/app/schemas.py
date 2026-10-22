from pydantic import BaseModel, Field, field_validator

class CreateRoom(BaseModel):
    name: str = Field(min_length=1, max_length=24)

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

class TiebreakerClue(BaseModel):
    text: str = Field(max_length=250)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Clue cannot be blank")
        return value

class TiebreakerGuessRequest(BaseModel):
    prompt_id: str
    author_guess_id: str
