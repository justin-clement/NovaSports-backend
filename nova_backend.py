from fastapi import FastAPI, Response, Cookie, HTTPException, BackgroundTasks, Depends, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from jose import jwt, ExpiredSignatureError, JWTError
from dotenv import load_dotenv
import pendulum
import os

from models import NewUser, NovaUser, Recommendation
from side_functions import clean, add_subscriber, verify_signature, manage_subscriptions
from db import database_connection


# LOAD ENVIRONMENT VARIABLES.
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
DB_URL = os.getenv("DB_URL")
NOVA_ADMIN = os.getenv("NOVA_ADMIN")
PAYSTACK_KEY = os.getenv("PAYSTACK_SECRET_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL")

# INSTANTIATE APPLICATION.
app = FastAPI(lifespan=manage_subscriptions)

# CONFIGURE CORS MIDDLEWARE.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

# PASSLIB CONTEXT TO HANDLE PASSWORDS.
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------- ROUTES ----------------------------

# ROUTE FOR HADNLING SIGN UP.
@app.post('/sign-up')
async def register_new_user(signup_details: NewUser, cursor=Depends(database_connection)):
    """Sign up new user."""

    create_user = "INSERT INTO Users (first_name, last_name, gender, email, " \
    "phone_number, nickname, password) VALUES (%s, %s, %s, %s, %s, %s, %s)"
    check_user = "SELECT 1 FROM Users WHERE nickname = %s OR email = %s OR phone_number = %s"
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
                'message': "This nickname is taken."}
    else:
        return {'status': True, 
                'message': "Nickname available."}


# ROUTE TO SEND A USER'S SUBSCRIPTION INFO TO THE FRONTEND.
@app.get('/subscriptions/{nickname}')
async def fetch_user_subscription(nickname: str, cursor=Depends(database_connection)):
    """User's subscription info is sent to the frontend, 
    to be displayed in the Subscriptions tab of their profile."""

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
                    'message': "Your subscription will expire soon."}
        else:
            return {'status': True, 'subscription': user_subscription, 
                    'message': ""}


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
        query = "SELECT subscription FROM Subscriptions WHERE nickname = %s;"
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
        return {'status': None, 
                'message': "Your access tag is expired, but don't worry. Just login again."}
    except JWTError:
        raise HTTPException(status_code=401, 
                            detail="We cannot read your access tag. Please login with a Novasports account.")
    


# ADMIN ENDPOINT FOR HANDLING RECOMMENDATION UPLOADS.
@app.post('/add-recommendations')
async def upload_recommendations(data: Recommendation, access_tag: str = Cookie(None), cursor=Depends(database_connection)):
    if access_tag is None:
        raise HTTPException(status_code=401, detail="You are not authorized to use this endpoint.")
    try:
        tag_information = jwt.decode(access_tag, SECRET_KEY, algorithms=["HS256"])
        if tag_information["role"] != "admin":
            raise HTTPException(status_code=403, detail="Access forbidden. This route is strictly admin-access.")
        else:
            query = "INSERT INTO Recommendations (league, home, away, recommendation) VALUES (%s, %s, %s, %s);"
            await cursor.execute(query, (data.league, data.home, data.away, data.recommendation))

            return {'status': True, 'message': "Recommendation uploaded."}
        
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, 
                            detail="Your access tag is expired. Re-login to upload recommendations.")
    except JWTError:
        raise HTTPException(status_code=403, 
                            detail="Your access tag could not be read. Login with a Novasports account.")


# WEBHOOK FOR CONFIRMING NEW SUBSCRIPTION PAYMENTS.    
@app.post('/webhook/new-subscription')
async def new_subscription(payment_data: dict, request: Request, background_tasks: BackgroundTasks, x_paystack_signature: str = Header(None)):  
    """Acknowledge subscription transaction."""

    request_body = await request.body()
    if x_paystack_signature is None:
        raise HTTPException(status_code=401, detail="You are not Paystack.")
    if not verify_signature(request_body, x_paystack_signature, PAYSTACK_KEY):
        raise HTTPException(status_code=401, detail="Signature confirmation failed.")
    
    user = payment_data["metadata"]["nickname"]
    amount = payment_data["data"]["amount"]
    
    background_tasks.add_task(add_subscriber, user, amount)
    return {'status': True}