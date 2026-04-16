import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv('.env')

# Create the SQLAlchemy engine
DATABASE_URL = os.getenv('DATABASE_URL' ,'')

engine = create_engine(DATABASE_URL)

# Create the sessionmaker for the database
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
