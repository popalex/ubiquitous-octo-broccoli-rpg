from time import sleep
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base
from main import app, get_db
from fastapi.testclient import TestClient
import os

# Use a file-based SQLite database for testing
TEST_DATABASE_URL = "sqlite:///./test.db"

# Remove the file if exists
if os.path.exists("./test.db"):
    os.remove("./test.db")

# Create the testing engine and session
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Override the get_db dependency to use the test database session
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

# Apply the override
app.dependency_overrides[get_db] = override_get_db

# Test client for FastAPI
client = TestClient(app)

@pytest.fixture(scope="function", autouse=True)
def setup_test_db():
    """
    Fixture to create all tables and ensure a clean database before each test.
    This uses SQLAlchemy's Base.metadata.create_all() to set up the schema for SQLite.
    """
    # Create the SQLite database file if it doesn't exist

    
    Base.metadata.create_all(bind=engine)
    
    yield  # Run the test
    
    # Teardown: Drop all tables after the test, but keep the file
    Base.metadata.drop_all(bind=engine)
    # if os.path.exists("./test.db"):
    #     os.remove("./test.db")
