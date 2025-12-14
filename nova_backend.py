from fastapi import FastAPI, Response, Cookie, HTTPException, BackgroundTasks, Depends, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import jwt
from dotenv import load_dotenv
import pendulum
import os

from models import NewUser, NovaUser, Recommendation
import side_functions as sf
from db import database_connection


# LOAD ENVIRONMENT VARIABLES.
load_dotenv()

SECRET_KEY = os.getenv("APPLICATION KEY")
DB_URL = os.getenv("DB_URL")
NOVA_ADMIN = os.getenv("NOVA_ADMIN")
PAYSTACK_KEY = os.getenv("PAYSTACK_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL")
TOKEN_ALGORITHM = os.getenv("TOKEN_ALGORITHM")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# CONFIGURE APPLICATION.
app = FastAPI(lifespan=sf.manage_subscriptions)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CONFIGURE CORS MIDDLEWARE.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)


# ---------------------------- ROUTES ----------------------------

# ROUTE FOR HADNLING SIGN UP.
@app.post('/sign-up')
@limiter.limit("7/minute")
async def register_new_user(request: Request, signup_details: NewUser, cursor=Depends(database_connection)):
    """Sign up a new user."""

    create_user = "INSERT INTO Users (first_name, last_name, gender, email, " \
    "phone_number, nickname, password) VALUES (%s, %s, %s, %s, %s, %s, %s);"
    check_user = "SELECT 1 FROM Users WHERE nickname = %s OR email = %s OR phone_number = %s;"
    await cursor.execute(check_user, (sf.clean(signup_details.nickname), sf.clean(signup_details.email), 
                                sf.clean(signup_details.phone_number)))
    user_exists = await cursor.fetchone()

    if user_exists is not None:
        return {'status': False, 
                'message': "An account already exists with the following email, nick or phone number."}
    else:
        hashed_password = sf.password_context.hash(signup_details.password)
        await cursor.execute(create_user, (sf.clean(signup_details.first_name), sf.clean(signup_details.last_name), 
                                        sf.clean(signup_details.gender), sf.clean(signup_details.email), 
                                        sf.clean(signup_details.phone_number), sf.clean(signup_details.nickname), 
                                        hashed_password))
        
        return {'status': True, 
                'message': f"{signup_details.nickname}, registered successfully."}


# ROUTE FOR HANDLING LOG IN.
@app.post('/sign-in/')
@limiter.limit("7/minute")
async def login(request: Request, login_details: NovaUser, response: Response, cursor=Depends(database_connection)):
    """Sign in a user."""

    nickname = sf.clean(login_details.nickname)
    query = "SELECT nickname, password FROM Users WHERE nickname = %s;"
    await cursor.execute(query, (nickname,))
    result = await cursor.fetchone()
    if result is None:
        return {'status': False, 
                'message': "This nickname wasn't found in our database. Check the name again."}
    elif not sf.password_context.verify(login_details.password, result[1]):
        return {'status': False, 
                'message': "Password incorrect."}
    else:
        tokens = sf.issue_tokens(nickname)

        response.set_cookie(
            key="access_tag", 
            value=tokens[0],
            max_age=3600, 
            httponly=True, 
            samesite="lax",
            path="/"
        )

        response.set_cookie(
            key="refresh_token", 
            value=tokens[1],
            max_age=3 * 24 * 3600, 
            httponly=True, 
            samesite="lax",
            path="/"
        )

        return {'status': True}


# ROUTE FOR CHECKING A NICKNAME'S AVAILABILITY.
@app.post('/check-nick')
@limiter.limit("10/minute")
async def check_nickname(request: Request, nickname: str, cursor=Depends(database_connection)):
    """Check if a nickname is available before account registration."""

    nick = sf.clean(nickname)
    query = "SELECT 1 FROM Users WHERE nickname = %s;"
    await cursor.execute(query, (nick,))
    result = await cursor.fetchone()
    if result is not None:
        return {'status': False, 
                'message': "This nickname is taken."}
    else:
        return {'status': True, 
                'message': "Nickname available."}


# ROUTE TO GET NEWS/INFO FOR ALL USERS.
@app.get('/info')
@limiter.limit("10/minute")
async def get_home_info(access_tag: str = Cookie(default=None), cursor=Depends(database_connection)):
    """Fetch news or other information to be displayed to all Supernova userson their home pages."""

    if access_tag is None or sf.verify_token(access_tag) is None:
        raise HTTPException(status_code=401, detail="Unauthorized.")
    
    query = "SELECT title, content FROM Information ORDER BY date DESC;"
    await cursor.execute(query)
    items = cursor.fetchall()   # returns a list of tuples.
    if not items:
        return {"status": False}
    else:
        articles = []
        for item in items:
            article = list(item)
            articles.append(article)

        return {
            "status": True, 
            "info": articles
            }


# ROUTE TO SEND A USER'S SUBSCRIPTION INFO TO THE FRONTEND.
@app.get('/subscriptions/{nickname}')
@limiter.limit("10/minute")
async def fetch_user_subscription(request: Request, nickname: str, cursor=Depends(database_connection), access_tag: str = Cookie(None)):
    """User's subscription info is sent to the frontend, 
    to be displayed in the Subscriptions tab of their profile."""

    if access_tag is None:
        raise HTTPException(status_code=401, detail="Unauthorized.")

    query = "SELECT subscription, expiry FROM Subscriptions WHERE nickname = %s;"
    await cursor.execute(query, (sf.clean(nickname),))
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
@limiter.limit("10/minute")
async def fetch_recommendations(request: Request, access_tag: str = Cookie(None), cursor=Depends(database_connection)):
    """Get matchday recommendations."""

    if access_tag is None or sf.verify_token(access_tag) is None:
        raise HTTPException(status_code=401, 
                            detail="Unauthorized. You currently have no access tag. Kindly log in with a Novasports account.")
    
    tag_from_client = sf.verify_token(access_tag)
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
    


# ADMIN ENDPOINT FOR HANDLING RECOMMENDATION UPLOADS.
@app.post('/add-recommendations')
@limiter.limit("10/minute")
async def upload_recommendations(request: Request, data: Recommendation, access_tag: str = Cookie(None), cursor=Depends(database_connection)):
    if access_tag is None or sf.verify_token(access_tag) is None:
        raise HTTPException(status_code=401, detail="You are not authorized to use this endpoint.")
    
    tag_information = sf.verify_token(access_tag)
    if tag_information["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access forbidden. This route is strictly admin-access.")
    else:
        query = "INSERT INTO Recommendations (league, home, away, recommendation) VALUES (%s, %s, %s, %s);"
        await cursor.execute(query, (data.league, data.home, data.away, data.recommendation))

        return {'status': True, 'message': "Recommendation uploaded."}
    
@app.delete("/recommendations")
@limiter.limit("7/minute")
async def clear_recommmendations(access_tag: str = Cookie(None), cursor=Depends(database_connection)):

    if access_tag is None or sf.verify_token(access_tag) is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    tag_information = sf.verify_token(access_tag)
    if tag_information["role"] != "admin" or tag_information["user"] != NOVA_ADMIN:
        raise HTTPException(status_code=403, detail="Forbidden.")
    else:
        query = "DELETE FROM Recommendations;"
        await cursor.execute(query)
        return {"status": True}

@app.get("/logout")
@limiter.limit("7/minute")
async def logout_user(response: Response, access_tag: str = Cookie(None)):
    """Log out a user by deleting their access and refresh tokens."""

    if access_tag is None or sf.verify_token(access_tag) is None:
        raise HTTPException(status_code=401, detail="Unauthorized.")

    response.delete_cookie(key="access_tag", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    
    return {'status': True}
        

# WEBHOOK FOR CONFIRMING NEW SUBSCRIPTION PAYMENTS.
@app.post(WEBHOOK_URL)
@limiter.limit("10/minute")
async def new_subscription(request: Request, payment_data: dict, background_tasks: BackgroundTasks, x_paystack_signature: str = Header(None)):  
    """Acknowledge subscription transaction."""

    request_body = await request.body()
    if x_paystack_signature is None:
        raise HTTPException(status_code=401, detail="You are not Paystack.")
    if not sf.verify_signature(request_body, x_paystack_signature, PAYSTACK_KEY):
        raise HTTPException(status_code=401, detail="Signature confirmation failed.")
    
    user = payment_data["metadata"].get("nickname")
    amount = payment_data["data"].get("amount")
    
    background_tasks.add_task(sf.add_subscriber, user, amount)
    return {'status': True}