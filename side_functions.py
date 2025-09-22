import sqlite3
import pendulum
from jose import jwt, ExpiredSignatureError, JWTError

def clean(string: str):
    """Remove space around a string and reduce to lower case."""
    
    try:
        cleaned = string.strip().lower()
        return cleaned
    except TypeError:
        return None
    
def refresh_subscriptions():
    """Check and update subscriptions in the database."""

    with sqlite3.connect("nova_subscriptions.db") as conn:
        cursor = conn.cursor()
        query = "DELETE FROM Subscriptions WHERE expiry < ?"
        current_time = pendulum.now("UTC").int_timestamp
        cursor.execute(query, (current_time))

        conn.commit()

def verify_access_tag(token: str, secret_key: str):
    """Verify the JWT of incoming requests."""

    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        return payload
    except ExpiredSignatureError:
        return None
    except JWTError:
        return None