# from psycopg_pool import AsyncConnectionPool
from dotenv import load_dotenv
import os
import psycopg

load_dotenv()

DB_URL = os.getenv("DB_URL")

# pool = AsyncConnectionPool(conninfo=DB_URL, min_size=2, max_size=24)

# async def database_connection():
#     async with pool.connection() as conn:
#         async with conn.cursor() as cursor:
#             yield cursor


# Users
nova_users = {
    "id": "INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,",
    "first_name": "TEXT NOT NULL,",
    "last_name": "TEXT NOT NULL,",
    "gender": "VARCHAR(2) NOT NULL,",
    "email": "VARCHAR(255) NOT NULL,",
    "phone_number": "VARCHAR(15) NOT NULL,",
    "nickname": "VARCHAR(255) NOT NULL,",
    "password": "VARCHAR(255) NOT NULL"
}

# Recommendations
nova_recommendations = {
    "id": "INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,",
    "league": "VARCHAR(50),",
    "home": "VARCHAR(33),",
    "away": "VARCHAR(33),",
    "recommendation": "TEXT"
}

# Subscriptions 
nova_subscriptions = {
    "nickname": "VARCHAR(255) PRIMARY KEY,",
    "subscription": "VARCHAR(7) NOT NULL,",
    "date_subscribed": "INTEGER NOT NULL,", 
    "expiry": "INTEGER NOT NULL"
}

tables = [nova_recommendations, nova_users, nova_subscriptions]
table_names = ["Recommendations", "Users", "Subscriptions"]

def test_db():
    """Function to test database connection and create tables if they don't exist."""
    try:
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cursor:
                for i, table in enumerate(tables):
                    table_name = table_names[i]
                    columns = " ".join([f"{col} {dtype}" for col, dtype in table.items()])
                    query = f"CREATE TABLE IF NOT EXISTS {table_name} ({columns});"
                    cursor.execute(query)
                    print(f"Ensured table {table_name} exists.")
    except Exception as e:
        print(f"Error connecting to the database: {e}") 

test_db()
    


