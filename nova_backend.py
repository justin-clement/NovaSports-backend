from fastapi import FastAPI, Response, Cookie, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
import pendulum
import psycopg
from passlib.context import CryptContext
from models import NewUser, NovaUser, Recommendation, Subscriber
from side_functions import clean, verify_access_tag
from db import database_connection
from jose import jwt, ExpiredSignatureError, JWTError
from dotenv import load_dotenv
import os

# THIS IS THE WEB BACKEND FOR NOVA SPORTS, HANDLING REGISTRATION, 
# LOGIN, GAME RECOMMENDATIONS, ETC.

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173/"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

# ENVIRONMENT VARIABLES.
SECRET_KEY = os.getenv("SECRET_KEY")
DB_URL = os.getenv("DB_URL")
NOVA_ADMIN = os.getenv("NOVA_ADMIN")

# PASSLIB CONTEXT TO HANDLE PASSWORDS.
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ROUTE FOR HADNLING SIGN UP.
@app.post('/sign-up')
async def register_new_user(signup_details: NewUser, cursor=Depends(database_connection)):
    """Register a new user."""

    create_user = "INSERT INTO Users (first_name, last_name, gender, email, " \
    "phone_number, nickname, password) VALUES (%s, %s, %s, %s, %s, %s, %s)"
    check_user = "SELECT 1 FROM NovaUsers WHERE nickname = %s OR email = %s OR phone_number = %s"
    await cursor.execute(check_user, (clean(signup_details.nickname), clean(signup_details.email), 
                                clean(signup_details.phone_number)))
    user_exists = await cursor.fetchone()

    if user_exists is not None:
        return {'status': False, 
                'message': "An account already exists with the following email, nick or phone number."}
    else:
        hashed_password = password_context.hash(signup_details.password)
        await cursor.execute(create_user, (clean(signup_details.first_name), clean(signup_details.last_name), 
                                        clean(signup_details.gender), clean(signup_details.email), 
                                        clean(signup_details.phone_number), clean(signup_details.nickname), 
                                        hashed_password))
        
        return {'status': True, 
                'message': f"{signup_details.nickname}, registered successfully."}

# ROUTE FOR HANDLING LOG IN.
@app.post('/sign-in/')
async def login(login_details: NovaUser, response: Response, cursor=Depends(database_connection)):
    """Sign in users."""

    nickname = clean(login_details.nickname)
    query = "SELECT nickname, password FROM Users WHERE nickname = %s"
    await cursor.execute(query, (nickname,))
    result = await cursor.fetchone()
    if result is None:
        return {'status': False, 
                'message': "This nickname wasn't found in our database. Check the name again."}
    elif not password_context.verify(login_details.password, result[1]):
        return {'status': False, 
                'message': "Password incorrect."}
    else:
        payload = {"user": nickname, 
                "role": f"{'user' if nickname != NOVA_ADMIN else 'admin'}", 
                "exp": pendulum.now('UTC').add(hours=1).int_timestamp}
        tag = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

        response.set_cookie(
            key="access_tag", 
            value=tag,
            max_age=3600,
            httponly=True,
            samesite="strict",
            secure=True,
            path="/"
        )

        return {'status': True}

# ROUTE FOR CHECKING A NICKNAME'S AVAILABILITY.
@app.post('/check-nick')
async def check_nickname(nickname: str, cursor=Depends(database_connection)):
    """Check if a nickname is available before account registration."""

    nick = clean(nickname)
    query = "SELECT 1 FROM Users WHERE nickname = %s;"
    await cursor.execute(query, (nick,))
    result = await cursor.fetchone()
    if result is not None:
        return {'status': False, 
                "message": "This nickname is taken."}
    else:
        return {'status': True, 
                "message": "Nickname available."}


# ROUTE FOR FETCHING MATCHDAY RECOMMMENDATIONS.
@app.get('/recommendations')
async def fetch_recommendation(access_tag: str = Cookie(None), cursor=Depends(database_connection)):
    """Get matchday recommendations."""

    if access_tag is None:
        raise HTTPException(status_code=401, 
                            detail="Unauthorized. You currently have no access tag. Kindly log in with a Novasports account.")
    try:
        tag_from_client = jwt.decode(access_tag, SECRET_KEY, algorithms=["HS256"])
        user_nick = tag_from_client.get("user")

        # CHECK THE USER'S SUBSCRIPTION FIRST.
        query = "SELECT subscription FROM Subscriptions WHERE nickname = %s"
        await cursor.execute(query, (user_nick,))
        result = await cursor.fetchone()
        if result is None:
            return {'status': False, 
                    'message': "You have to be subscribed to receive recommendations."}
        else:
            user_subscription = result[0]            
            query = "SELECT * FROM Recommendations ORDER BY recommendation ASC;"
            await cursor.execute(query)
            results = await cursor.fetchall()
            if not results:
                return {'status': False, 
                        'message': "No recommendations yet."}
            else:
                recommendations = []
                total_games = len(results)
                games_for_user = 0
                if user_subscription == "NOVA A":
                    games_for_user = round(0.5 * total_games)
                elif user_subscription == "NOVA B":
                    games_for_user = total_games

                for result in results[:games_for_user]:
                    item = {"key": result[0], "league": result[1], 
                            "home": result[2], "away": result[3], 
                            "recommendation": result[4]}
                    recommendations.append(item)

                return {'status': True, 'array': recommendations}
            
    except ExpiredSignatureError:
        return {'status': False, 
                'message': "Your access tag is expired, but don't worry. Just login again."}
    except JWTError:
        raise HTTPException(status_code=401, 
                            detail="We cannot read your access tag. Please login with a Novasports account.")
    

# ROUTE TO SEND A USER'S SUBSCRIPTION INFO TO THE FRONTEND.
@app.get('/subscriptions/{nickname}')
async def fetch_user_subscription(nickname: str):
    """User's subscription info is sent to the frontend, 
    to be displayed in the Subscriptions tab of their profile."""

    async with psycopg.AsyncConnection.connect(DB_URL) as conn:
        cursor = conn.cursor()
        query = "SELECT subscription, expiry FROM Subscriptions WHERE nickname = %s"
        await cursor.execute(query, (clean(nickname),))
        result = await cursor.fetchone()
        if result is None:
            return {'status': False, 
                    'message': "No active subscription."}
        else:
            user_subscription = result[0]
            expiry = pendulum.from_timestamp(result[1], tz="UTC")
            current_date = pendulum.now("UTC")

            if current_date > expiry:
                return {'status': False, 
                        'message': "Your subscription is expired. Renew to keep receiving hot matchday recommendations."}
            elif current_date.add(days=7) > expiry:
                return {'status': True, 'subscription': user_subscription, 
                        'message': "Your Nova subscription will expire soon."}
            else:
                return {'status': True, 'subscription': user_subscription, 
                        'message': ""}


# FUNCTION TO RECORD A NEW SUBSCRIBER IN THE DATABASE.
async def add_subscriber(nickname: str, amount_paid: int):
    """Record new subscriber."""

    NOVA_A = 450000
    NOVA_B = 800000

    nick = clean(nickname)
    user_subscription = ""

    async with psycopg.AsyncConnection.connect(DB_URL) as conn:
        async with conn.cursor() as cursor:
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
            await conn.commit()

# ADMIN ENDPOINT FOR HANDLING RECOMMENDATION UPLOADS.
@app.post('/add-recommendations')
async def upload_recommendations(data: Recommendation, access_tag: str = Cookie(None)):
    if access_tag == None:
        raise HTTPException(status_code=401, detail="You are not authorized to use this endpoint.")
    try:
        tag_information = jwt.decode(access_tag, SECRET_KEY, algorithms=["HS256"])
        if tag_information["role"] != "admin":
            raise HTTPException(status_code=403, detail="Access forbidden. This route is strictly admin-access.")
        else:
            async with psycopg.AsyncConnection.connect(DB_URL) as conn:
                cursor = conn.cursor()
                query = "INSERT INTO Recommendations (league, home, away, recommendation) VALUES (%s, %s, %s, %s)"
                await cursor.execute(query, (data.league, data.home, data.away, data.recommendation))
                await conn.commit()

                return {"message": "Recommendation uploaded."}
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Your access tag is expired. Re-login to upload recommendations.")
    except JWTError:
        raise HTTPException(status_code=403, detail="Your access tag could not be read. Login with a Novasports account.")

# WEBHOOK TO CONFIRM NEW SUBSCRIPTION PAYMENT.    
@app.post('/webhook/new-subscription')
async def new_subscription(payment_data: Subscriber, background_tasks: BackgroundTasks):
    """Acknowledge subscription transaction."""
    await background_tasks.add_task(add_subscriber, payment_data)
    return {"status": True}