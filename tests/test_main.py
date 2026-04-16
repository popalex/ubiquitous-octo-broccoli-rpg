from .conftest import client  # Import the test client
import pytest

# Test for posting an author
def test_post_author():
    author_data = {
        "name": "John",
        "surname": "Doe",
        "age": 45
    }

    response = client.post("/author/", json=author_data)

    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["name"] == author_data["name"]
    assert data["surname"] == author_data["surname"]
    assert data["age"] == author_data["age"]

# Test for getting all authors
def test_get_author():
    author_data = {
        "name": "John",
        "surname": "Doe",
        "age": 45
    }

    response = client.post("/author/", json=author_data)

    response = client.get("/author/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)  # Ensure it's a list
    assert len(data) > 0  # Ensure there is at least one author

# Test for posting a book
def test_post_book():
    author_data = {
        "name": "Jane",
        "surname": "Smith",
        "age": 30
    }
    # First, we need to create an author to associate with the book
    author_response = client.post("/author/", json=author_data)
    author_id = author_response.json()["id"]

    book_data = {
        "title": "Test Book",
        "rating": 4.5,
        "author_id": author_id
    }

    response = client.post("/book/", json=book_data)

    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["title"] == book_data["title"]
    assert data["rating"] == book_data["rating"]
    assert data["author_id"] == book_data["author_id"]

# Test for getting all books
def test_get_book():
    response = client.get("/book/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)  # Ensure it's a list
    assert len(data) >= 0  # The list can be empty if no books are added

# Test for a single book retrieval (if you want to add this)
def test_get_single_book():
    author_data = {
        "name": "Alice",
        "surname": "Johnson",
        "age": 35
    }
    # Create an author
    author_response = client.post("/author/", json=author_data)
    author_id = author_response.json()["id"]

    book_data = {
        "title": "Single Test Book",
        "rating": 5.0,
        "author_id": author_id
    }
    # Create a book
    book_response = client.post("/book/", json=book_data)
    book_id = book_response.json()["id"]

    response = client.get(f"/book/{book_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == book_id
    assert data["title"] == book_data["title"]
    assert data["rating"] == book_data["rating"]
    assert data["author_id"] == book_data["author_id"]

# Test for invalid book creation (optional)
def test_post_book_invalid():
    book_data = {
        "title": "Invalid Book",
        "rating": "Not a float",
        "author_id": 999
    }

    response = client.post("/book/", json=book_data)
    assert response.status_code == 400 

    book_data = {
        "rating": 20.2,
        "author_id": 1
    }

    response = client.post("/book/", json=book_data)
    assert response.status_code == 400  # Expect a validation error

# Test for invalid author creation (optional)
def test_post_author_invalid():

    author_data = {
        "name": "",  # Invalid name
        "surname": "Doe",
        "age": 45
    }

    response = client.post("/author/", json=author_data)
    assert response.status_code == 400  # Expect a validation error
