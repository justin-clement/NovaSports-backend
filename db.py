from psycopg_pool import AsyncConnectionPool
from dotenv import load_dotenv
import os

load_dotenv()

DB_URL = os.getenv("DB_URL")

pool = AsyncConnectionPool(conninfo=DB_URL, min_size=2, max_size=24)

async def database_connection():
    async with pool.connection() as conn:
        async with conn.cursor() as cursor:
            yield cursor


# Users
users = {
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
recommendations = {
    "id": "INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,",
    "league": "VARCHAR(50),",
    "home": "VARCHAR(33),",
    "away": "VARCHAR(33),",
    "recommendation": "TEXT"
}

# Subscriptions 
subscriptions = {
    "nickname": "VARCHAR(255) PRIMARY KEY,",
    "subscription": "VARCHAR(7) NOT NULL,",
    "date_subscribed": "INTEGER NOT NULL,", 
    "expiry": "INTEGER NOT NULL"
}

tables = [recommendations, users, subscriptions]
table_names = ["Recommendations", "Users", "Subscriptions"]