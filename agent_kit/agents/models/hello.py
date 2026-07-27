from pydantic import BaseModel, Field, field_validator


class HelloInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class HelloOutput(BaseModel):
    greeting: str

    @field_validator("greeting")
    @classmethod
    def greeting_not_empty(cls, v):
        if not v:
            raise ValueError("greeting must not be empty")
        return v
