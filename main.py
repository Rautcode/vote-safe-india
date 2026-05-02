from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import sqlite3
import json
import urllib.request
import hashlib
from datetime import datetime

app = FastAPI(title="VoteSafe India API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Setup
DB_PATH = "votesafe.db"

# 2026 Election Data & States
INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", 
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", 
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", 
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", 
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Lakshadweep", "Delhi", "Puducherry", "Ladakh", "Jammu and Kashmir"
]

CONSTITUENCY_DATA = {
    "PUNE WEST": {"margin": 2419, "budget": "45.2 Cr", "date": "Nov 20, 2026", "center": "St. Mary's School, Room 4"},
    "THIRUVANANTHAPURAM": {"margin": 8900, "budget": "65.8 Cr", "date": "Apr 9, 2026", "center": "Cotton Hill Girls School"},
    "GUWAHATI": {"margin": 5400, "budget": "89.2 Cr", "date": "Apr 9, 2026", "center": "Cotton University Hall"},
    "CHENNAI SOUTH": {"margin": 1500, "budget": "38.5 Cr", "date": "Apr 23, 2026", "center": "Anna University Polling Station"},
    "KOLKATA DAKSHIN": {"margin": 12400, "budget": "112 Cr", "date": "Apr 23, 2026", "center": "Ballygunge Government High School"},
    "JADAVPUR": {"margin": 3200, "budget": "77.5 Cr", "date": "Apr 29, 2026", "center": "Jadavpur Vidyapith Booth 12"},
    "DEFAULT": {"margin": 5000, "budget": "50 Cr", "date": "May 4, 2026", "center": "Govt Higher Secondary School"}
}

FAQ_DATA = [
    {"q": "How do I find my polling booth?", "a": "You can use the 'CHECK MY STATUS' tool or send an SMS with 'EPIC <ID>' to 1950."},
    {"q": "What is Form 17B?", "a": "It is the form used to record a 'Tendered Ballot' if someone else has already voted in your name."},
    {"q": "Can I vote with an Aadhaar card?", "a": "Yes, if your name is in the electoral roll, you can use Aadhaar or 11 other approved documents."},
    {"q": "What is a Tendered Ballot?", "a": "A paper ballot provided when a voter's identity is verified but their vote is already cast."}
]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, state TEXT, district TEXT, pincode TEXT, epic TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS incidents
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_name TEXT, timestamp TEXT, msg TEXT)''')
    conn.commit()
    conn.close()

init_db()

class UserOnboard(BaseModel):
    name: str
    state: str
    district: str
    pincode: str = None
    epic: str = None

class IncidentLog(BaseModel):
    user_name: str
    msg: str

class ComplaintRequest(BaseModel):
    situation_id: int
    user_name: str
    constituency: str
    booth_number: str

class StatusRequest(BaseModel):
    name: str
    state: str
    district: str
    epic: str = None

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    current_dir = os.path.dirname(os.path.realpath(__file__))
    file_path = os.path.join(current_dir, "frontend", "index.html")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/v1/states")
async def get_states():
    return {"status": "success", "states": INDIAN_STATES}

def generate_booth_data(pincode: str, district: str, state: str):
    # Deterministic generation based on pincode
    seed = int(hashlib.md5(str(pincode).encode()).hexdigest(), 16) % 10000
    prefixes = ["Govt Primary School", "Zilla Parishad School", "Municipal Corporation Building", "Community Hall", "Panchayat Office", "Higher Secondary School", "Town Hall", "Public Library Building"]
    prefix = prefixes[seed % len(prefixes)]
    room = (seed % 15) + 1
    
    # Random realistic date in 2026 based on state hash
    state_seed = int(hashlib.md5(str(state).encode()).hexdigest(), 16) % 100
    month = ["Apr", "May", "Nov"][state_seed % 3]
    day = (state_seed % 28) + 1
    
    # Check if we have hardcoded accurate data in CONSTITUENCY_DATA
    dist_upper = district.upper()
    if dist_upper in CONSTITUENCY_DATA:
        return CONSTITUENCY_DATA[dist_upper]
    
    return {
        "margin": 1000 + (seed % 9000),
        "budget": f"{10 + (seed % 90)}.5 Cr",
        "date": f"{month} {day}, 2026",
        "center": f"{prefix}, {district.title()}, Room {room}"
    }

@app.get("/api/v1/resolve_pincode/{pincode}")
async def resolve_pincode(pincode: str):
    try:
        req = urllib.request.Request(
            f"https://api.postalpincode.in/pincode/{pincode}",
            headers={'User-Agent': 'VoteSafeIndia/1.0'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if data and data[0]["Status"] == "Success":
                po = data[0]["PostOffice"][0]
                return {
                    "status": "success",
                    "state": po.get("State", ""),
                    "district": po.get("District", ""),
                    "region": po.get("Name", "")
                }
    except Exception as e:
        print("API resolution error:", e)
    return {"status": "error", "message": "Could not resolve pincode."}

@app.post("/api/v1/onboard")
async def onboard_user(req: UserOnboard):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (name, state, district, pincode, epic) VALUES (?, ?, ?, ?, ?)",
              (req.name, req.state, req.district, req.pincode, req.epic))
    conn.commit()
    conn.close()
    
    data = generate_booth_data(req.pincode, req.district, req.state)
    
    return {"status": "success", "message": "User onboarded", "constituency_data": data}

@app.get("/api/v1/incidents/{user_name}")
async def get_incidents(user_name: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT timestamp, msg FROM incidents WHERE user_name = ? ORDER BY id DESC", (user_name,))
    rows = c.fetchall()
    conn.close()
    return {"status": "success", "incidents": [dict(r) for r in rows]}

@app.post("/api/v1/incidents")
async def log_incident(req: IncidentLog):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO incidents (user_name, timestamp, msg) VALUES (?, ?, ?)",
              (req.user_name, datetime.now().isoformat(), req.msg))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Incident logged"}

@app.get("/api/v1/faqs")
async def get_faqs():
    return {"status": "success", "faqs": FAQ_DATA}

@app.post("/api/v1/complaint/generate")
async def generate_complaint(req: ComplaintRequest):
    if req.situation_id == 3:
        text = f"""TO THE PRESIDING OFFICER
Booth No: {req.booth_number}
Constituency: {req.constituency}

SUBJECT: DEMAND FOR TENDERED BALLOT UNDER RULE 49P (2026 ELECTIONS)

Sir/Madam,
I, {req.user_name}, arrived at the booth to cast my vote, only to be told that someone has already voted against my name. 

I possess valid identification. Under Rule 49P of the Conduct of Elections Rules, 1961, I demand my right to cast a Tendered Ballot. Please provide me with Form 17B immediately.

Denial of this right is a violation of my constitutional right under Article 326.

Signed,
{req.user_name}
Date: {datetime.now().strftime('%Y-%m-%d')}"""
        return {"status": "success", "complaint_text": text}
    
    return {"status": "error", "message": "Situation not supported in this demo yet."}

@app.post("/api/v1/status/briefing")
async def get_briefing(req: StatusRequest):
    # For status briefing we might not have pincode directly in req unless we add it,
    # let's fetch it from DB based on name and epic, or fallback
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT pincode FROM users WHERE name = ? ORDER BY id DESC LIMIT 1", (req.name,))
    row = c.fetchone()
    conn.close()
    
    pincode = row['pincode'] if row and row['pincode'] else "110001"
    const_data = generate_booth_data(pincode, req.district, req.state)
    
    return {
        "status": "success",
        "data": {
            "name": req.name.upper(),
            "constituency": f"{req.state.upper()} — {req.district.upper()}",
            "booth_location": const_data["center"],
            "election_date": const_data["date"],
            "documents_needed": "EPIC or Aadhaar",
            "polling_hours": "7:00 AM - 6:00 PM"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
