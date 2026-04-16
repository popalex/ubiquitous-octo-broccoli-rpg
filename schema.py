from pydantic import BaseModel, field_validator, validator

# Schema for input when creating an author (no ID)
class AuthorCreate(BaseModel):
    name: str
    surname: str
    age: int

    class Config:
        # orm_mode = True
        from_attributes = True

    @field_validator('name', 'surname')
    @classmethod
    def name_surname_not_empty(cls, v):
        if not v:
            raise ValueError('Name and Surname cannot be empty')
        return v

# Schema for output after creating an author (with ID)
class AuthorResponse(BaseModel):
    id: int  # ID will be included in the response
    name: str
    surname: str
    age: int

    class Config:
        # orm_mode = True
        from_attributes = True

# No changes needed for books if they're fine as-is
class Book(BaseModel):
    title: str
    rating: float
    author_id: int

    class Config:
        # orm_mode = True
        from_attributes = True

    @field_validator('title', 'rating')
    @classmethod
    def name_surname_not_empty(cls, v):
        if not v:
            raise ValueError('Title and Rating cannot be empty')
        return v

class FullBook(BaseModel):
    id: int
    title: str
    rating: float
    author_id: int

    class Config:
        # orm_mode = True
        from_attributes = True
