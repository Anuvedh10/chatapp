import random
import smtplib
import os
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
from bson import ObjectId

import cloudinary
import cloudinary.uploader
import firebase_admin
from firebase_admin import credentials, messaging

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── MongoDB ───────────────────────────────────────────
client = MongoClient(os.environ["MONGO_URI"])
db = client["chatapp"]
users_col = db["users"]
messages_col = db["messages"]
tokens_col = db["tokens"]
otps_col = db["otps"]

# ── Firebase Admin ────────────────────────────────────
cred = credentials.Certificate("/etc/secrets/serviceAccountKey.json")
firebase_admin.initialize_app(cred)

# ── Cloudinary ────────────────────────────────────────
cloudinary.config(
    cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
    api_key=os.environ["CLOUDINARY_API_KEY"],
    api_secret=os.environ["CLOUDINARY_API_SECRET"],
)

# ── Models ────────────────────────────────────────────
class User(BaseModel):
    username: str
    password: str

class UserWithEmail(BaseModel):
    username: str
    password: str
    email: str

class OtpRequest(BaseModel):
    email: str

class OtpVerify(BaseModel):
    email: str
    otp: str

class Message(BaseModel):
    sender: str
    receiver: str
    text: str

class TokenData(BaseModel):
    username: str
    token: str

class ReactionData(BaseModel):
    username: str
    emoji: str

class EditData(BaseModel):
    text: str

class ForwardData(BaseModel):
    sender: str
    receiver: str
    text: str

# ── OTP Email Helper ──────────────────────────────────
def send_otp_email(to_email: str, otp: str):
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    print(f"[OTP] Sending to: {to_email}")
    print(f"[OTP] Gmail user: {gmail_user}")
    print(f"[OTP] Password set: {bool(gmail_password)}")

    if not gmail_user or not gmail_password:
        raise Exception("GMAIL_USER or GMAIL_APP_PASSWORD missing!")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "NexaChat – Your Verification Code"
    msg["From"] = f"NexaChat <{gmail_user}>"
    msg["To"] = to_email

    html = f"""
    <html>
    <body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:30px;margin:0">
      <div style="max-width:420px;margin:auto;background:white;
                  border-radius:16px;padding:36px;box-shadow:0 2px 12px rgba(0,0,0,0.08)">
        <div style="text-align:center;margin-bottom:24px">
          <h1 style="color:#1A1A2E;font-size:28px;margin:0">NexaChat</h1>
          <p style="color:#888;font-size:14px;margin:4px 0 0">Verification Code</p>
        </div>
        <p style="color:#444;font-size:15px">
          Use the code below to verify your Gmail and create your NexaChat account.
        </p>
        <div style="background:#f0f0f5;border-radius:12px;padding:24px;
                    text-align:center;margin:24px 0">
          <span style="font-size:40px;font-weight:bold;letter-spacing:12px;
                       color:#1A1A2E;font-family:monospace">{otp}</span>
        </div>
        <p style="color:#888;font-size:13px;text-align:center">
          This code expires in <b>10 minutes</b>.<br>
          If you didn't request this, you can safely ignore this email.
        </p>
        <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
        <p style="color:#bbb;font-size:11px;text-align:center">
          NexaChat · Contact us on Instagram @anuvedhh
        </p>
      </div>
    </body>
    </html>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        print("[OTP] Trying port 587...")
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, to_email, msg.as_string())
            print("[OTP] Sent via port 587 ✅")
    except Exception as e1:
        print(f"[OTP] Port 587 failed: {e1}")
        try:
            print("[OTP] Trying port 465...")
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
                server.login(gmail_user, gmail_password)
                server.sendmail(gmail_user, to_email, msg.as_string())
                print("[OTP] Sent via port 465 ✅")
        except Exception as e2:
            print(f"[OTP] Port 465 failed: {e2}")
            raise Exception(f"Both ports failed. 587: {e1} | 465: {e2}")

# ── OTP Endpoints ─────────────────────────────────────
@app.post("/send-otp")
def send_otp(data: OtpRequest):
    email = data.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address")

    if users_col.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    otp = str(random.randint(100000, 999999))
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)

    otps_col.update_one(
        {"email": email},
        {"$set": {
            "email": email,
            "otp": otp,
            "expires_at": expires_at,
            "verified": False
        }},
        upsert=True
    )

    try:
        send_otp_email(email, otp)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    return {"message": "OTP sent successfully"}

@app.post("/verify-otp")
def verify_otp(data: OtpVerify):
    email = data.email.strip().lower()
    record = otps_col.find_one({"email": email})

    if not record:
        raise HTTPException(status_code=400, detail="No OTP found for this email. Request a new one.")

    if datetime.datetime.utcnow() > record["expires_at"]:
        otps_col.delete_one({"email": email})
        raise HTTPException(status_code=400, detail="OTP expired. Request a new one.")

    if record["otp"] != data.otp.strip():
        raise HTTPException(status_code=400, detail="Incorrect OTP. Try again.")

    otps_col.update_one({"email": email}, {"$set": {"verified": True}})
    return {"message": "OTP verified successfully"}

# ── Auth ──────────────────────────────────────────────
@app.post("/register")
def register(data: UserWithEmail):
    email = data.email.strip().lower()

    otp_record = otps_col.find_one({"email": email})
    if not otp_record or not otp_record.get("verified"):
        raise HTTPException(
            status_code=400,
            detail="Email not verified. Please complete OTP verification first."
        )

    if users_col.find_one({"username": data.username}):
        raise HTTPException(status_code=400, detail="Username already exists")

    if users_col.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    users_col.insert_one({
        "username": data.username,
        "password": data.password,
        "email": email,
        "bio": "",
        "avatar_color": "",
        "photo_url": "",
        "created_at": datetime.datetime.utcnow().isoformat(),
    })

    otps_col.delete_one({"email": email})
    return {"message": "Registration Successful"}

@app.post("/login")
def login(user: User):
    u = users_col.find_one({"username": user.username, "password": user.password})
    if not u:
        raise HTTPException(status_code=401, detail="Invalid Username or Password")
    return {
        "message": "Login Successful",
        "username": u.get("username", ""),
        "email": u.get("email", ""),
    }

@app.put("/change-password")
def change_password(data: dict):
    username = data.get("username")
    old_password = data.get("old_password")
    new_password = data.get("new_password")
    u = users_col.find_one({"username": username, "password": old_password})
    if not u:
        raise HTTPException(status_code=401, detail="Current password incorrect")
    users_col.update_one(
        {"username": username},
        {"$set": {"password": new_password}}
    )
    return {"message": "Password changed"}

# ── Users ─────────────────────────────────────────────
@app.get("/users")
def get_users():
    users = users_col.find({}, {"_id": 0, "username": 1})
    return [u["username"] for u in users]

@app.get("/conversations/{username}")
def get_conversations(username: str):
    msgs = messages_col.find(
        {"$or": [{"sender": username}, {"receiver": username}]},
        {"_id": 0}
    )
    contacts = set()
    for m in msgs:
        if m["sender"] == username:
            contacts.add(m["receiver"])
        else:
            contacts.add(m["sender"])
    return list(contacts)

# ── Profile ───────────────────────────────────────────
@app.get("/profile/{username}")
def get_profile(username: str):
    u = users_col.find_one(
        {"username": username},
        {"_id": 0, "password": 0}
    )
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "username": u.get("username", ""),
        "bio": u.get("bio", ""),
        "avatar_color": u.get("avatar_color", ""),
        "photo_url": u.get("photo_url", ""),
    }

@app.put("/profile/{username}")
def update_profile(username: str, data: dict):
    update = {}
    if "bio" in data:
        update["bio"] = data["bio"]
    if "avatar_color" in data:
        update["avatar_color"] = data["avatar_color"]
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    users_col.update_one(
        {"username": username},
        {"$set": update}
    )
    return {"message": "Profile updated"}

@app.post("/profile/{username}/photo")
async def upload_profile_photo(username: str, file: UploadFile = File(...)):
    try:
        contents = await file.read()
        result = cloudinary.uploader.upload(
            contents,
            folder="chatapp/avatars",
            public_id=f"avatar_{username}",
            overwrite=True,
            resource_type="image",
        )
        url = result["secure_url"]
        users_col.update_one(
            {"username": username},
            {"$set": {"photo_url": url}}
        )
        return {"url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── FCM Token ─────────────────────────────────────────
@app.post("/register-token")
def register_token(data: TokenData):
    tokens_col.update_one(
        {"username": data.username},
        {"$set": {"username": data.username, "token": data.token}},
        upsert=True
    )
    return {"status": "ok"}

# ── Version ───────────────────────────────────────────
@app.get("/version")
def get_version():
    return {"min_version": "1.0.0", "latest_version": "1.0.0"}

# ── Push Notification ─────────────────────────────────
def send_push(receiver: str, sender: str, text: str):
    try:
        doc = tokens_col.find_one({"username": receiver})
        if not doc or not doc.get("token"):
            return
        preview = text
        if text.startswith("↩ ") and "\n" in text:
            preview = text.split("\n", 1)[1]
        if text.startswith("[IMAGE]:"):
            preview = "📷 Photo"
        elif text.startswith("[VIDEO]:"):
            preview = "🎥 Video"
        elif text.startswith("[VOICE]:"):
            preview = "🎤 Voice message"
        elif text.startswith("[FORWARD]:"):
            preview = "↪ Forwarded: " + text.replace("[FORWARD]:", "")[:50]

        message = messaging.Message(
            notification=messaging.Notification(
                title=sender,
                body=preview[:100],
            ),
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="chatapp_channel",
                    sound="default",
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default"),
                ),
            ),
            token=doc["token"],
        )
        messaging.send(message)
    except Exception as e:
        print(f"Push failed: {e}")

# ── Messages ──────────────────────────────────────────
@app.post("/send")
def send_message(msg: Message):
    doc = {
        "sender": msg.sender,
        "receiver": msg.receiver,
        "text": msg.text,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "read": False,
        "deleted": False,
        "edited": False,
        "reactions": {},
    }
    result = messages_col.insert_one(doc)
    send_push(msg.receiver, msg.sender, msg.text)
    return {"message": "sent", "id": str(result.inserted_id)}

@app.get("/chat/{user1}/{user2}")
def get_chat(user1: str, user2: str):
    msgs = messages_col.find(
        {
            "$or": [
                {"sender": user1, "receiver": user2},
                {"sender": user2, "receiver": user1}
            ],
            "deleted": {"$ne": True}
        }
    )
    result = []
    for m in msgs:
        result.append({
            "id": str(m["_id"]),
            "sender": m["sender"],
            "receiver": m["receiver"],
            "text": m["text"],
            "timestamp": m.get("timestamp", ""),
            "read": m.get("read", False),
            "edited": m.get("edited", False),
            "reactions": m.get("reactions", {}),
        })
    return result

@app.post("/read/{sender}/{receiver}")
def mark_read(sender: str, receiver: str):
    messages_col.update_many(
        {"sender": sender, "receiver": receiver, "read": False},
        {"$set": {"read": True}}
    )
    return {"message": "marked read"}

@app.delete("/message/{message_id}")
def delete_message(message_id: str):
    try:
        messages_col.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": {"deleted": True}}
        )
        return {"message": "deleted"}
    except:
        raise HTTPException(status_code=400, detail="Invalid message id")

@app.put("/message/{message_id}/edit")
def edit_message(message_id: str, data: EditData):
    try:
        messages_col.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": {"text": data.text, "edited": True}}
        )
        return {"message": "edited"}
    except:
        raise HTTPException(status_code=400, detail="Invalid message id")

@app.post("/message/{message_id}/react")
def react_message(message_id: str, data: ReactionData):
    try:
        msg = messages_col.find_one({"_id": ObjectId(message_id)})
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        reactions = msg.get("reactions", {})
        current = reactions.get(data.username)
        if current == data.emoji:
            del reactions[data.username]
        else:
            reactions[data.username] = data.emoji
        messages_col.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": {"reactions": reactions}}
        )
        return {"reactions": reactions}
    except HTTPException:
        raise
    except:
        raise HTTPException(status_code=400, detail="Invalid message id")

@app.post("/forward")
def forward_message(data: ForwardData):
    doc = {
        "sender": data.sender,
        "receiver": data.receiver,
        "text": f"[FORWARD]:{data.text}",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "read": False,
        "deleted": False,
        "edited": False,
        "reactions": {},
    }
    result = messages_col.insert_one(doc)
    send_push(data.receiver, data.sender, f"[FORWARD]:{data.text}")
    return {"message": "forwarded", "id": str(result.inserted_id)}

@app.get("/search/{user1}/{user2}")
def search_messages(user1: str, user2: str, q: str):
    if not q or len(q) < 1:
        return []
    msgs = messages_col.find(
        {
            "$or": [
                {"sender": user1, "receiver": user2},
                {"sender": user2, "receiver": user1}
            ],
            "deleted": {"$ne": True},
            "text": {"$regex": q, "$options": "i"}
        }
    )
    result = []
    for m in msgs:
        result.append({
            "id": str(m["_id"]),
            "sender": m["sender"],
            "receiver": m["receiver"],
            "text": m["text"],
            "timestamp": m.get("timestamp", ""),
            "read": m.get("read", False),
            "edited": m.get("edited", False),
            "reactions": m.get("reactions", {}),
        })
    return result

@app.post("/upload")
async def upload_file(
    sender: str = Form(...),
    receiver: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        ext = file.filename.split(".")[-1].lower()
        allowed_image = ["jpg", "jpeg", "png", "gif", "webp"]
        allowed_video = ["mp4", "mov", "avi", "mkv"]
        allowed_audio = ["m4a", "aac", "mp3", "wav", "ogg"]
        allowed = allowed_image + allowed_video + allowed_audio

        if ext not in allowed:
            raise HTTPException(status_code=400, detail="File type not allowed")

        is_video = ext in allowed_video
        is_audio = ext in allowed_audio
        resource_type = "video" if (is_video or is_audio) else "image"

        file_bytes = await file.read()
        result = cloudinary.uploader.upload(
            file_bytes,
            resource_type=resource_type,
            folder="chatapp",
            public_id=f"{sender}_{datetime.datetime.utcnow().timestamp()}",
        )

        file_url = result["secure_url"]
        if is_video:
            msg_text = f"[VIDEO]:{file_url}"
        elif is_audio:
            msg_text = f"[VOICE]:{file_url}"
        else:
            msg_text = f"[IMAGE]:{file_url}"

        doc = {
            "sender": sender,
            "receiver": receiver,
            "text": msg_text,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "read": False,
            "deleted": False,
            "edited": False,
            "reactions": {},
        }
        insert_result = messages_col.insert_one(doc)
        send_push(receiver, sender, msg_text)
        return {
            "message": "uploaded",
            "id": str(insert_result.inserted_id),
            "url": file_url
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Typing ────────────────────────────────────────────
@app.get("/typing/{sender}/{receiver}")
def typing_status(sender: str, receiver: str):
    key = f"{sender}_to_{receiver}"
    doc = db["typing"].find_one({"key": key})
    if not doc:
        return {"typing": False}
    elapsed = (datetime.datetime.utcnow() - doc["updated"]).total_seconds()
    return {"typing": elapsed < 3}

@app.post("/typing/{sender}/{receiver}")
def set_typing(sender: str, receiver: str):
    key = f"{sender}_to_{receiver}"
    db["typing"].update_one(
        {"key": key},
        {"$set": {"key": key, "updated": datetime.datetime.utcnow()}},
        upsert=True
    )
    return {"ok": True}

@app.delete("/clear-chat/{user1}/{user2}")
def clear_chat(user1: str, user2: str):
    messages_col.update_many(
        {"$or": [
            {"sender": user1, "receiver": user2},
            {"sender": user2, "receiver": user1}
        ]},
        {"$set": {"deleted": True}}
    )
    return {"message": "Chat cleared"}
