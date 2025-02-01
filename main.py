from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from typing import Dict, List
from datetime import datetime, timedelta
import asyncio
import websockets
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
import secrets
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
logged_in_users = {}  
active_connections = {}
# MongoDB connection
MONGO_URI = "mongodb://localhost:27017"
client = AsyncIOMotorClient(MONGO_URI)
db = client["chat_db"]
users_collection = db["users"]

# Pydantic model
class User(BaseModel):
    username: str

CHAT_DURATION = timedelta(minutes=15)
active_chats = {}  # Dictionary to store active chat sessions
chat_expiry = {}  # Dictionary to store chat expiry times

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can specify your frontend URL here
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Generate and assign tokens dynamically
def generate_token(username: str) -> str:
    token = secrets.token_hex(16)
    return token


async def authenticate(token: str) -> str:
    # Check if token exists in the MongoDB users collection
    user = await users_collection.find_one({"token": token})
    if user:
        return user["username"]
    return None


# Active logins (Tracks logged-in users in MongoDB)
async def update_login_status(username: str, logged_in: bool):
    await users_collection.update_one(
        {"username": username},
        {"$set": {"logged_in": logged_in}},
    )


@app.post("/register/{username}")
async def register_user(username: str):
    existing_user = await users_collection.find_one({"username": username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Generate token and store it with user info in MongoDB
    token = generate_token(username)
    user_data = {"username": username, "token": token, "logged_in": False}
    await users_collection.insert_one(user_data)
    
    return {"token": token}


@app.post("/login/{username}")
async def login(username: str):
    # Check if the user exists in the database
    user = await users_collection.find_one({"username": username})

    if not user:
        raise HTTPException(status_code=400, detail="User not found")

    # Update the logged_in field to True after login
    await users_collection.update_one(
        {"username": username},
        {"$set": {"logged_in": True}}
    )

    logged_in_users[username] = datetime.utcnow()
    return {"message": "Login successful", "token": user["token"]}

@app.post("/logout/{username}")
async def logout_user(username: str):
    await update_login_status(username, False)
    return {"message": "Logout successful", "username": username}

async def auto_logout():
    while True:
        now = datetime.utcnow()
        for user, login_time in list(logged_in_users.items()):
            if now - login_time > timedelta(minutes=1):
                del logged_in_users[user]  # Remove user
                if user in active_connections:
                    await active_connections[user].close()  # Close WebSocket
                    del active_connections[user]
                print(f"User {user} has been logged out due to inactivity.")
        
        await asyncio.sleep(60)  # Check every 60 seconds

@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(auto_logout())  # Start auto-logout task on server startup



@app.get("/logged-in-users")
async def get_logged_in_users():
    # Return a list of usernames who are logged in
    logged_in_users = await users_collection.find({"logged_in": True}).to_list(None)
    return [user["username"] for user in logged_in_users]


@app.websocket("/notifications")
async def notifications(websocket: WebSocket):
    await websocket.accept()
    while True:
        # Send the list of logged-in users whenever there's a change
        logged_in_users = await users_collection.find({"logged_in": True}).to_list(None)
        await websocket.send_json([user["username"] for user in logged_in_users])
        await asyncio.sleep(5)  # Send every 5 seconds


@app.websocket("/chat/{username}/{partner}")
async def websocket_endpoint(websocket: WebSocket, username: str, partner: str):
    await websocket.accept()
    
    # Store the WebSocket connection
    active_connections[username] = websocket

    try:
        while True:
            data = await websocket.receive_text()
            if partner in active_connections:
                await active_connections[partner].send_text(data)
    except WebSocketDisconnect:
        del active_connections[username]



    # Accept the WebSocket connection
    await websocket.accept()

    # Ensure the users are not already in an active chat
    if username in active_chats or partner in active_chats:
        await websocket.send_text("One of you is already in a chat. Disconnect and try again.")
        await websocket.close(code=1008)  # 1008: Policy violation
        return


    # Start chat session
    active_chats[username] = {"socket": websocket, "partner": partner}
    active_chats[partner] = {"socket": websocket, "partner": username}

    expiry_time = datetime.utcnow() + CHAT_DURATION
    chat_expiry[username] = expiry_time
    chat_expiry[partner] = expiry_time


    # Notify both users of the successful connection
    await websocket.send_text(f"Connected with {partner}")
    if partner in active_chats:
        await active_chats[partner]["socket"].send_text(f"Connected with {username}")

    try:
        while datetime.utcnow() < chat_expiry[username]:
            try:
                # Receive a message from the current user
                message = await websocket.receive_text()

                # Send the message to the partner
                partner_socket = active_chats[partner]["socket"]
                await partner_socket.send_text(f"{username}: {message}")
            except WebSocketDisconnect as e:
                print(f"Error during message receive: {e}")
                await handle_disconnect(username, partner, websocket)
                break
            except Exception as e:
                print(f"Error during message exchange: {e}")
                break

    except asyncio.CancelledError as e:
        print(f"Chat session was cancelled: {e}")
        pass

    finally:
        # Cleanup when chat ends (either expired or one user disconnects)
        await cleanup_chat(username, partner, websocket)

@app.websocket("/chat/{username}/{chat_partner}")
async def chat_endpoint(websocket: WebSocket, username: str, chat_partner: str):
    await websocket.accept()
    
    # Store the WebSocket connection
    active_connections[username] = websocket
    print(f"User {username} connected.")

    try:
        while True:
            data = await websocket.receive_text()
            if chat_partner in active_connections:
                await active_connections[chat_partner].send_text(f"{username}: {data}")
            else:
                await websocket.send_text(f"{chat_partner} is not online.")
    except WebSocketDisconnect:
        print(f"User {username} disconnected.")
        del active_connections[username]

async def handle_disconnect(username: str, partner: str, websocket: WebSocket):
    """Handles user disconnection and notifies the partner."""
    if username in active_chats:
        try:
            partner_socket = active_chats[partner]["socket"]
            await partner_socket.send_text(f"{username} has disconnected.")
        except Exception:
            pass  # Ignore if partner is disconnected

        await websocket.close()
        active_chats.pop(username, None)
        active_chats.pop(partner, None)
        chat_expiry.pop(username, None)
        chat_expiry.pop(partner, None)


async def cleanup_chat(username: str, partner: str, websocket: WebSocket):
    """Cleans up the chat session after completion or disconnect."""
    try:
        if partner in active_chats:
            partner_socket = active_chats[partner]["socket"]
            await partner_socket.send_text("Chat session ended.")
            await partner_socket.close()
            del active_chats[partner]
            del chat_expiry[partner]
    except Exception as e:
        print(f"Error during cleanup for partner {partner}: {e}")

    # Handle cleanup for the current user
    try:
        await websocket.send_text("Chat session ended.")
        await websocket.close()
        del active_chats[username]
        del chat_expiry[username]
    except Exception as e:
        print(f"Error during cleanup for user {username}: {e}")
