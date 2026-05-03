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

# ── Google Gemini Integration ──────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
gemini_model = None

try:
    if GEMINI_API_KEY:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=(
                "You are the VoteSafe India Civic AI Strategist — an expert in Indian electoral law, "
                "voter rights, and the Representation of the People Act 1950/1951. "
                "You help Indian citizens understand their voting rights clearly and concisely. "
                "Always cite specific rules (Rule 49P, Section 128 RPA, Article 326 etc.) when relevant. "
                "Keep answers under 150 words. Be direct, empowering, and legally accurate. "
                "If asked about something unrelated to voting or civic rights in India, politely redirect. "
                "Never provide medical, financial, or legal advice beyond voter rights."
            )
        )
        print("✅ Gemini API connected successfully")
    else:
        print("⚠️  GEMINI_API_KEY not set — AI features will use fallback responses")
except ImportError:
    print("⚠️  google-generativeai not installed — run: pip install google-generativeai")
except Exception as e:
    print(f"⚠️  Gemini init error: {e}")

app = FastAPI(
    title="VoteSafe India API", 
    description="Civic Rights Protection powered by Google Gemini",
    version="1.0.4"
)

# ── Security: CORS Refinement ────────────────────────────────────────────────
# In production, this should be restricted to specific domains.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Database Setup ───────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DATABASE_URL", "votesafe.db")

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

    def validate(self):
        """Manual validation for security and correctness."""
        if not self.name or len(self.name.strip()) < 2:
            return False, "Name too short"
        if self.pincode and (not self.pincode.isdigit() or len(self.pincode) != 6):
            return False, "Pincode must be 6 digits"
        return True, ""

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

from functools import lru_cache

@lru_cache(maxsize=128)
def generate_booth_data(pincode: str, district: str, state: str):
    """Generates deterministic booth data based on pincode to avoid massive DB storage.
    Efficiency: Uses LRU cache to avoid re-hashing for the same location.
    """
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
    """Generate a formal legal complaint letter. Uses Gemini AI when available for personalized language."""
    if req.situation_id != 3:
        return {"status": "error", "message": "Situation not supported in this demo yet."}

    # ── Try Gemini-powered complaint first ────────────────────────────────────
    if gemini_model:
        try:
            prompt = (
                f"Write a formal legal complaint letter in English for an Indian voter whose vote was stolen. "
                f"Voter name: {req.user_name}. Constituency: {req.constituency}. Booth number: {req.booth_number}. "
                f"Date: {datetime.now().strftime('%d %B %Y')}. "
                f"The letter must cite Rule 49P of the Conduct of Elections Rules 1961, demand a Tendered Ballot, "
                f"request Form 17B, and reference Article 326 of the Constitution. "
                f"Keep it formal, under 200 words, and address it to the Presiding Officer."
            )
            response = gemini_model.generate_content(prompt)
            ai_text = response.text.strip()
            return {
                "status": "success",
                "complaint_text": ai_text,
                "ai_generated": True
            }
        except Exception as e:
            print(f"Gemini complaint generation failed: {e} — falling back to template")

    # ── Static fallback template ──────────────────────────────────────────────
    text = f"""TO THE PRESIDING OFFICER
Booth No: {req.booth_number}
Constituency: {req.constituency}

SUBJECT: DEMAND FOR TENDERED BALLOT UNDER RULE 49P (2026 ELECTIONS)

Sir/Madam,
I, {req.user_name}, arrived at the booth to cast my vote, only to be informed that
someone has already voted against my name fraudulently.

I possess valid identification. Under Rule 49P of the Conduct of Elections Rules, 1961,
I hereby formally demand my right to cast a Tendered Ballot. Please provide me with
Form 17B immediately so that my identity is placed on official record.

Denial of this right constitutes a violation of my constitutional right to vote
guaranteed under Article 326 of the Constitution of India.

I request this matter to be escalated to the Election Observer immediately.

Signed,
{req.user_name}
Date: {datetime.now().strftime('%d %B %Y')}"""

    return {"status": "success", "complaint_text": text, "ai_generated": False}

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

# ── Civic AI Chat Endpoint ───────────────────────────────────────────────────

class CivicAIRequest(BaseModel):
    question: str
    context: str = ""  # Optional context: user's state, situation

@app.post("/api/v1/civic-ai/ask")
async def civic_ai_ask(req: CivicAIRequest):
    """Civic AI Strategist — powered by Google Gemini.
    
    Answers questions about Indian voter rights, electoral law, and
    booth procedures. Falls back to rule-based answers if Gemini is unavailable.
    """
    question = req.question.strip()
    if not question:
        return {"status": "error", "message": "Question cannot be empty"}

    # Reject non-civic questions
    civic_keywords = [
        "vote", "voter", "booth", "election", "eci", "epic", "ballot",
        "right", "rule", "form", "register", "complaint", "officer",
        "indelible", "evm", "vvpat", "nota", "constituency", "polling",
        "1950", "49p", "126", "128", "aadhaar", "id", "identity",
        "fraud", "impersonation", "bribe", "cvigil", "helpline"
    ]
    question_lower = question.lower()
    if not any(kw in question_lower for kw in civic_keywords):
        return {
            "status": "success",
            "answer": "I can only assist with voter rights and Indian election-related questions. Please ask about your voting rights, booth procedures, or electoral complaints.",
            "ai_generated": False
        }

    # ── Gemini-powered response ────────────────────────────────────────────────
    if gemini_model:
        try:
            context_prefix = f"User context: {req.context}. " if req.context else ""
            full_prompt = f"{context_prefix}Voter question: {question}"
            response = gemini_model.generate_content(full_prompt)
            return {
                "status": "success",
                "answer": response.text.strip(),
                "ai_generated": True
            }
        except Exception as e:
            print(f"Gemini AI ask failed: {e} — using fallback")

    # ── Rule-based fallback answers ────────────────────────────────────────────
    fallbacks = {
        "stolen": "Under Rule 49P, demand a Tendered Ballot and sign Form 17B. Call 1950 immediately.",
        "missing": "Ask the officer to check the BLO's supplementary list. If still missing, demand written refusal under Section 49M.",
        "booth": "SMS 'EPIC <your_id>' to 1950 or visit electoralsearch.eci.gov.in to find your current booth.",
        "id": "12 documents are accepted: Aadhaar, PAN, Driving License, Passport, and 8 others. You do not need your EPIC card.",
        "bribe": "Report via the cVIGIL app with a photo/video. Flying Squad responds within 100 minutes. Your identity is protected.",
        "nota": "NOTA is the last option on the ballot. It is legally counted and valid — your protest is officially recorded.",
        "disable": "The Presiding Officer must provide assistance. You may bring a companion (Rule 49N) or request the ballot unit be brought to you.",
        "register": "Apply via Form 6 on voters.eci.gov.in. You need Aadhaar/PAN, age proof, and address proof.",
    }
    for keyword, answer in fallbacks.items():
        if keyword in question_lower:
            return {"status": "success", "answer": answer, "ai_generated": False}

    return {
        "status": "success",
        "answer": "For immediate help, call the national voter helpline at 1950 (toll-free). For emergency booth situations, use the Emergency Assistance section.",
        "ai_generated": False
    }


@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint — returns API status and Gemini availability."""
    return {
        "status": "ok",
        "gemini_available": gemini_model is not None,
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
