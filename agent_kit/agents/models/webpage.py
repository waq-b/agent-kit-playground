from pydantic import BaseModel, Field, field_validator


class WebpageInput(BaseModel):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def url_is_http(cls, v):
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


class WebpageOutput(BaseModel):
    title: str
    summary: str
    key_points: list[str]

    @field_validator("summary")
    @classmethod
    def summary_not_empty(cls, v):
        if not v:
            raise ValueError("summary must not be empty")
        return v
