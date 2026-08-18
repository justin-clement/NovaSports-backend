from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import database_connection
from dotenv import load_dotenv
from passlib.context import CryptContext
from psycopg import AsyncCursor
import os
import jwt
import hmac
import hashlib
import pendulum


load_dotenv()

PAYSTACK_KEY = os.getenv("PAYSTACK_KEY")
APP_KEY = os.getenv("APP_KEY")
ALGORITHM = os.getenv("ALGORITHM")

scheduler = AsyncIOScheduler()

def clean(string: str):
    """Remove space around a string and reduce to lower case."""
    
    try:
        cleaned = string.strip().lower()
        return cleaned
    except TypeError:
        return None
    
async def refresh_subscriptions(cursor: AsyncCursor =Depends(database_connection)):
    """Check and update subscriptions in the database."""

    query = "DELETE FROM Subscriptions WHERE expiry < %s;"
    current_time = pendulum.now("UTC").int_timestamp
    await cursor.execute(query, (current_time,))

@asynccontextmanager
async def manage_subscriptions(app: FastAPI):
    """Scheduler function, to be passed into FastAPI as a lifespan."""

    scheduler.add_job(refresh_subscriptions, "cron", hour=23, minute=59)
    scheduler.start()
    yield
    scheduler.shutdown()

async def add_subscriber(nickname: str, amount_paid: int, cursor: AsyncCursor =Depends(database_connection)):
    """Record new subscriber."""

    NOVA_A = 450000
    NOVA_B = 800000

    nick = clean(nickname)
    user_subscription = ""

    if amount_paid == NOVA_A:
        user_subscription = "A"
    elif amount_paid == NOVA_B:
        user_subscription = "B"

    record_subscription_query = """
    INSERT INTO Subscriptions (nickname, subscription, date_subscribed, expiry) 
    VALUES (%s, %s, %s, %s);
    """

    subscription_start = pendulum.now('UTC')
    subscription_end = subscription_start.add(days=30)

    await cursor.execute(record_subscription_query, (nick, user_subscription, 
                        subscription_start.int_timestamp, subscription_end.int_timestamp))

def verify_signature(request_body: bytes, signature: str, secret_key: str) -> bool:
    """Use HMAC to verify Paystack as the originator of the webhook request."""

    computed_signature = hmac.new(
        key=secret_key.encode(), 
        msg=request_body, 
        digestmod=hashlib.sha512
    ).hexdigest()

    return hmac.compare_digest(computed_signature, signature)

def issue_tokens(nickname: str) -> tuple[str, str] | None:
    """Issue an access and refresh token."""
    
    try:
        access_payload = {
            "user": nickname, 
            "role": "user", 
            "exp": pendulum.now('UTC').add(hours=1).int_timestamp
        }
    
        refresh_payload = {
            "user": nickname, 
            "role": "user", 
            "exp": pendulum.now('UTC').add(days=3).int_timestamp
        }
    
        access_token = jwt.encode(access_payload, APP_KEY, algorithm="HS256")
        refresh_token = jwt.encode(refresh_payload, APP_KEY, algorithm="HS256")
    
        return {
            "access": access_token, 
            "refresh": refresh_token
        }
    except Exception:
        return None
    

def verify_token(token: str) -> dict | None:
    """Verify the validity of a client's token."""
    
    try:
        payload = jwt.decode(token, APP_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# PASSLIB CONTEXT TO HANDLE PASSWORDS.
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")