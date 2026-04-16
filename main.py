import logging
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi_sqlalchemy import DBSessionMiddleware, db
from database import engine, SessionLocal  
from alembic.config import Config
from alembic import command
from sqlalchemy.orm import Session

from schema import AuthorCreate, AuthorResponse, Book as SchemaBook, FullBook

from models import Book as ModelBook
from models import Author as ModelAuthor

import os
from dotenv import load_dotenv

def run_all_migrations(DATABASE_URL = os.getenv('DATABASE_URL', '')) -> None:
    os.environ['FROM_MAIN'] = 'true'
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    run_migrations(os.path.join(BASE_DIR, 'alembic'), DATABASE_URL)

def run_migrations(script_location: str, dsn: str) -> None:
    logging.warning('Running DB migrations in %r on %r', script_location, dsn)
    alembic_cfg = Config('alembic.ini')
    alembic_cfg.set_main_option('script_location', script_location)
    alembic_cfg.set_main_option('sqlalchemy.url', dsn)
    command.upgrade(alembic_cfg, 'head')

load_dotenv('.env')

app = FastAPI()

DATABASE_URL = os.getenv('DATABASE_URL', '')

# Add the DBSessionMiddleware with your production database URL
# And avoid csrftokenError
app.add_middleware(DBSessionMiddleware, db_url=DATABASE_URL)

# Dependency to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    print("Running migrations...")
    run_all_migrations()
    
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content=jsonable_encoder({"detail": exc.errors(), "body": exc.body}),
    )

@app.exception_handler(ResponseValidationError)
async def response_validation_exception_handler(request: Request, exc: ResponseValidationError):  # Fixed
    return JSONResponse(
        status_code=400,
        content=jsonable_encoder({"detail": exc.errors(), "body": exc.body}),
    )

@app.get("/")
async def root():
    return {"message": "hello world"}

@app.post('/book/', response_model=FullBook)
async def post_book(book: SchemaBook, db: Session = Depends(get_db)):
    db_book = ModelBook(title=book.title, rating=book.rating, author_id=book.author_id)
    db.add(db_book)
    db.commit()
    db.refresh(db_book)
    return db_book

@app.get('/book/')
async def get_book(db: Session = Depends(get_db)):
    books = db.query(ModelBook).all()
    return books

@app.get('/book/{id}')
async def get_book_by_id(id: int, db: Session = Depends(get_db)):
    book = db.query(ModelBook).filter(ModelBook.id == id).first()
    if book is None:
        raise HTTPException(status_code=404, detail='Book not found')
    return book

@app.post('/author/', response_model=AuthorResponse)  # Using AuthorResponse schema for the response
async def post_author(author: AuthorCreate, db: Session = Depends(get_db)):  # Using AuthorCreate schema for the input (no ID)
    db_author = ModelAuthor(name=author.name, surname=author.surname, age=author.age)
    db.add(db_author)
    db.commit()
    db.refresh(db_author)  # Refresh to get the auto-generated ID from the database
    return db_author  # This will return the author with the ID included

@app.get('/author/')
async def get_author(db: Session = Depends(get_db)):
    authors = db.query(ModelAuthor).all()
    return authors

@app.get('/author/{id}')
async def get_author_by_id(id: int, db: Session = Depends(get_db)):
    author = db.query(ModelAuthor).filter(ModelAuthor.id == id).first()
    if author is None:
        raise HTTPException(status_code=404, detail='Author not found')
    return author

# To run locally
if __name__ == '__main__':
    print("Starting server...")
    uvicorn.run(app, host='0.0.0.0', port=8000)
