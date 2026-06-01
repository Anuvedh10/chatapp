from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json
import os
import uuid
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USERS_FILE = "users.json"
MESSAGES_FILE = "messages.json"
TYPING_FILE = "typing.json"

def load(file):
    if not os.path.exists(file):
        return []
    with open(file, "r") as f:
        return json.load(f)

def load_dict(file):
    if not os.path.exists(file):
        return {}
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
    type: Optional[str] = "text"      # "text" or "voice"
    audioData: Optional[str] = None   # base64 audio string

class TypingStatus(BaseModel):
    sender: str
    receiver: str

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

@app.get("/users")
def get_users():
    users = load(USERS_FILE)
    return [u["username"] for u in users]

@app.post("/send")
def send_message(msg: Message):
    messages = load(MESSAGES_FILE)
    entry = {
        "id": str(uuid.uuid4()),
        "sender": msg.sender,
        "receiver": msg.receiver,
        "text": msg.text,
        "type": msg.type or "text",
        "audioData": msg.audioData,
        "timestamp": datetime.utcnow().isoformat(),
        "read": False,
    }
    messages.append(entry)
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

@app.delete("/message/{msg_id}")
def delete_message(msg_id: str):
    messages = load(MESSAGES_FILE)
    messages = [m for m in messages if m.get("id") != msg_id]
    save(MESSAGES_FILE, messages)
    return {"message": "deleted"}

@app.post("/read/{sender}/{receiver}")
def mark_read(sender: str, receiver: str):
    messages = load(MESSAGES_FILE)
    for msg in messages:
        if msg["sender"] == sender and msg["receiver"] == receiver:
            msg["read"] = True
    save(MESSAGES_FILE, messages)
    return {"message": "marked read"}

@app.post("/typing/{sender}/{receiver}")
def set_typing(sender: str, receiver: str):
    typing = load_dict(TYPING_FILE)
    key = f"{sender}_{receiver}"
    typing[key] = datetime.utcnow().isoformat()
    save(TYPING_FILE, typing)
    return {"message": "ok"}

@app.get("/typing/{sender}/{receiver}")
def get_typing(sender: str, receiver: str):
    typing = load_dict(TYPING_FILE)
    key = f"{sender}_{receiver}"
    if key not in typing:
        return {"typing": False}
    last = datetime.fromisoformat(typing[key])
    diff = (datetime.utcnow() - last).total_seconds()
    return {"typing": diff < 4}
