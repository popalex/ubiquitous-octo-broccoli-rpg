# Generate migrations (online)

On Postgres 15, give rights on public schema for the current user:

```sql
GRANT ALL ON SCHEMA public TO dev;
```

Next, generate the migrations:

```shell
alembic revision --autogenerate -m "New Migration"
```

# Update the database (run migrations)

```shell
alembic upgrade head
```

# Run the API

```shell
uvicorn main:app --reload
```

Next, go to SWAGGER UI http://localhost:8000/docs

# Docker

Build the image:

```shell
docker build -t fastapi .
```

Then, run the image:

```shell
docker run -e DATABASE_URL='postgresql://driver://user:pass@localhost/dbname' -p 8080:8080 fastapi
```

# Links
https://www.educative.io/answers/how-to-use-postgresql-database-in-fastapi