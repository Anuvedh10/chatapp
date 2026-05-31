from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USERS_FILE = "users.json"
MESSAGES_FILE = "messages.json"

def load(file):
    if not os.path.exists(file):
        return []
    with open(file, "r") as f:
        return json.load(f)

def save(file, data):
    with open(file, "w") as f:
        json.dump(data, f)

class User(BaseModel):
    username: str
    password: str

class Message(BaseModel):
    sender: str
    receiver: str
    text: str

@app.get("/users")
def get_users():
    users = load(USERS_FILE)
    return [u["username"] for u in users]

@app.post("/register")
def register(user: User):
    users = load(USERS_FILE)
    for u in users:
        if u["username"] == user.username:
            raise HTTPException(status_code=400, detail="Username already exists")
    users.append(user.dict())
    save(USERS_FILE, users)
    return {"message": "Registration Successful"}

@app.post("/login")
def login(user: User):
    users = load(USERS_FILE)
    for u in users:
        if u["username"] == user.username and u["password"] == user.password:
            return {"message": "Login Successful"}
    raise HTTPException(status_code=401, detail="Invalid Username or Password")

@app.post("/send")
def send_message(msg: Message):
    messages = load(MESSAGES_FILE)
    messages.append(msg.dict())
    save(MESSAGES_FILE, messages)
    return {"message": "sent"}

@app.get("/chat/{user1}/{user2}")
def get_chat(user1: str, user2: str):
    messages = load(MESSAGES_FILE)
    return [
        msg for msg in messages
        if (msg["sender"] == user1 and msg["receiver"] == user2)
        or (msg["sender"] == user2 and msg["receiver"] == user1)
    ]
