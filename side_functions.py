import pendulum
from fastapi import FastAPI
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends
from db import database_connection
import hmac
import hashlib



scheduler = AsyncIOScheduler()

def clean(string: str):
    """Remove space around a string and reduce to lower case."""
    
    try:
        cleaned = string.strip().lower()
        return cleaned
    except TypeError:
        return None
    
async def refresh_subscriptions(cursor=Depends(database_connection)):
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

async def add_subscriber(nickname: str, amount_paid: int, cursor=Depends(database_connection)):
    """Record new subscriber."""

    NOVA_A = 450000
    NOVA_B = 800000

    nick = clean(nickname)
    user_subscription = ""

    if amount_paid == NOVA_A:
        user_subscription = "NOVA A"
    elif amount_paid == NOVA_B:
        user_subscription = "NOVA B"

    query = "INSERT INTO Subscriptions (nickname, subscription, date_subscribed, expiry) " \
    "VALUES (%s, %s, %s, %s)"

    subscription_start = pendulum.now('UTC')
    subscription_end = subscription_start.add(days=28)

    await cursor.execute(query, (nick, user_subscription, 
                        subscription_start.int_timestamp, subscription_end.int_timestamp))

def verify_webhook(request_body: bytes, signature: str, secret_key: str) -> bool:
    """Use HMAC to verify Paystack as the originator of the webhook request."""

    computed_signature = hmac.new(
        key=secret_key.encode(), 
        msg=request_body, 
        digestmod=hashlib.sha512
    ).hexdigest()

    return hmac.compare_digest(computed_signature, signature)

