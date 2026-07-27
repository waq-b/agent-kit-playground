from pydantic import BaseModel, Field, field_validator


class NewsInput(BaseModel):
    keywords: list[str] = Field(min_length=1)

    @field_validator("keywords")
    @classmethod
    def keywords_valid(cls, v):
        for kw in v:
            if not (1 <= len(kw) <= 100):
                raise ValueError("each keyword must be 1-100 characters")
        return v


class NewsItem(BaseModel):
    title: str
    source: str
    url: str
    relevance_note: str

    @field_validator("title", "source", "url", "relevance_note")
    @classmethod
    def not_empty(cls, v):
        if not v:
            raise ValueError("field must not be empty")
        return v


class NewsOutput(BaseModel):
    items: list[NewsItem]
