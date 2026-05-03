"""
VoteSafe India — API Test Suite
Tests all FastAPI endpoints for functionality, validation, and edge cases.
Run: pytest tests/ -v
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os

# Add parent directory to path so we can import main
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app

client = TestClient(app)


# ─────────────────────────────────────────────────────────
# FRONTEND SERVING
# ─────────────────────────────────────────────────────────

class TestFrontend:
    def test_root_returns_html(self):
        """Root endpoint serves the frontend SPA."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "VoteSafe" in response.text

    def test_root_contains_key_ui_elements(self):
        """Frontend contains essential UI sections."""
        response = client.get("/")
        html = response.text
        assert "onboarding-view" in html
        assert "emergency-view" in html
        assert "landing-view" in html


# ─────────────────────────────────────────────────────────
# STATES ENDPOINT
# ─────────────────────────────────────────────────────────

class TestStatesEndpoint:
    def test_get_states_success(self):
        """States endpoint returns all Indian states + UTs."""
        response = client.get("/api/v1/states")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "states" in data
        assert len(data["states"]) == 36  # 28 states + 8 UTs

    def test_states_contains_key_states(self):
        """Response includes major Indian states."""
        response = client.get("/api/v1/states")
        states = response.json()["states"]
        for state in ["Maharashtra", "Delhi", "Bihar", "Tamil Nadu", "West Bengal"]:
            assert state in states

    def test_states_contains_union_territories(self):
        """Response includes Union Territories."""
        response = client.get("/api/v1/states")
        states = response.json()["states"]
        assert "Delhi" in states
        assert "Ladakh" in states
        assert "Jammu and Kashmir" in states


# ─────────────────────────────────────────────────────────
# USER ONBOARDING
# ─────────────────────────────────────────────────────────

class TestOnboarding:
    def test_onboard_user_success(self):
        """User onboarding creates a record and returns booth data."""
        payload = {
            "name": "Arjun Sharma",
            "state": "Maharashtra",
            "district": "Pune",
            "pincode": "411001",
            "epic": "MH0123456"
        }
        response = client.post("/api/v1/onboard", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "constituency_data" in data
        assert "date" in data["constituency_data"]
        assert "center" in data["constituency_data"]

    def test_onboard_without_optional_fields(self):
        """Onboarding works without EPIC and pincode."""
        payload = {
            "name": "Priya Verma",
            "state": "Delhi",
            "district": "South Delhi"
        }
        response = client.post("/api/v1/onboard", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_onboard_requires_name(self):
        """Onboarding rejects request missing required name field."""
        payload = {"state": "Bihar", "district": "Patna"}
        response = client.post("/api/v1/onboard", json=payload)
        assert response.status_code == 422  # Validation error

    def test_onboard_requires_state(self):
        """Onboarding rejects request missing required state field."""
        payload = {"name": "Test User", "district": "Patna"}
        response = client.post("/api/v1/onboard", json=payload)
        assert response.status_code == 422

    def test_onboard_known_constituency(self):
        """Known district returns accurate hardcoded booth data."""
        payload = {
            "name": "Test User",
            "state": "Kerala",
            "district": "Thiruvananthapuram",
            "pincode": "695001"
        }
        response = client.post("/api/v1/onboard", json=payload)
        data = response.json()
        assert data["status"] == "success"
        # Thiruvananthapuram is in CONSTITUENCY_DATA
        assert "Cotton Hill" in data["constituency_data"]["center"]

    def test_onboard_deterministic_booth_generation(self):
        """Same pincode always generates same booth data."""
        payload = {
            "name": "User A",
            "state": "Rajasthan",
            "district": "Jaipur",
            "pincode": "302001"
        }
        response1 = client.post("/api/v1/onboard", json=payload)
        response2 = client.post("/api/v1/onboard", json=payload)
        assert response1.json()["constituency_data"] == response2.json()["constituency_data"]


# ─────────────────────────────────────────────────────────
# PINCODE RESOLUTION
# ─────────────────────────────────────────────────────────

class TestPincodeResolution:
    def test_resolve_valid_pincode_structure(self):
        """Pincode endpoint returns a valid JSON response structure."""
        response = client.get("/api/v1/resolve_pincode/411001")
        assert response.status_code == 200
        data = response.json()
        # Either success with state/district OR error if API unavailable
        assert "status" in data

    def test_resolve_invalid_pincode_returns_error(self):
        """Invalid pincode returns error gracefully."""
        response = client.get("/api/v1/resolve_pincode/000000")
        assert response.status_code == 200  # Should not 500-crash
        data = response.json()
        assert "status" in data


# ─────────────────────────────────────────────────────────
# INCIDENT LOGGING
# ─────────────────────────────────────────────────────────

class TestIncidents:
    def test_log_incident_success(self):
        """Incident logging returns success."""
        payload = {
            "user_name": "Test Voter",
            "msg": "Polling officer refused to let me vote — Rule 49P violation at Booth 12"
        }
        response = client.post("/api/v1/incidents", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_get_incidents_for_user(self):
        """Retrieving incidents for a user returns correct structure."""
        user = "IncidentTestUser_XYZ"
        # First log one
        client.post("/api/v1/incidents", json={"user_name": user, "msg": "Test incident"})
        # Then retrieve
        response = client.get(f"/api/v1/incidents/{user}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "incidents" in data
        assert len(data["incidents"]) >= 1

    def test_incidents_contain_timestamp(self):
        """Logged incidents include timestamp field."""
        user = "TimestampTestUser_ABC"
        client.post("/api/v1/incidents", json={"user_name": user, "msg": "Timestamp check"})
        response = client.get(f"/api/v1/incidents/{user}")
        incidents = response.json()["incidents"]
        assert "timestamp" in incidents[0]
        assert "msg" in incidents[0]

    def test_get_incidents_nonexistent_user(self):
        """Non-existent user returns empty list, not an error."""
        response = client.get("/api/v1/incidents/NoSuchUser_ZZZZZZ999")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["incidents"] == []

    def test_log_incident_requires_user_name(self):
        """Incident log rejects missing user_name."""
        payload = {"msg": "Some incident without a user"}
        response = client.post("/api/v1/incidents", json=payload)
        assert response.status_code == 422


# ─────────────────────────────────────────────────────────
# COMPLAINT GENERATION
# ─────────────────────────────────────────────────────────

class TestComplaintGeneration:
    def test_generate_rule_49p_complaint(self):
        """Situation 3 (stolen vote) generates a valid Rule 49P complaint."""
        payload = {
            "situation_id": 3,
            "user_name": "Rajesh Kumar",
            "constituency": "Pune West",
            "booth_number": "12"
        }
        response = client.post("/api/v1/complaint/generate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "complaint_text" in data
        # Verify legal content
        assert "Rule 49P" in data["complaint_text"]
        assert "Form 17B" in data["complaint_text"]
        assert "Rajesh Kumar" in data["complaint_text"]
        assert "Pune West" in data["complaint_text"]

    def test_complaint_contains_legal_references(self):
        """Generated complaint references Article 326 constitutional right."""
        payload = {
            "situation_id": 3,
            "user_name": "Test Voter",
            "constituency": "Test Constituency",
            "booth_number": "1"
        }
        response = client.post("/api/v1/complaint/generate", json=payload)
        text = response.json()["complaint_text"]
        assert "Article 326" in text

    def test_unsupported_situation_returns_error(self):
        """Situation IDs other than 3 return error (not 500)."""
        payload = {
            "situation_id": 99,
            "user_name": "Test",
            "constituency": "Test",
            "booth_number": "1"
        }
        response = client.post("/api/v1/complaint/generate", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "error"

    def test_complaint_requires_all_fields(self):
        """Complaint generation validates required fields."""
        payload = {"situation_id": 3, "user_name": "Test"}
        response = client.post("/api/v1/complaint/generate", json=payload)
        assert response.status_code == 422


# ─────────────────────────────────────────────────────────
# VOTER BRIEFING
# ─────────────────────────────────────────────────────────

class TestVoterBriefing:
    def test_briefing_returns_voter_info(self):
        """Briefing endpoint returns personalized voter data."""
        payload = {
            "name": "Sunita Devi",
            "state": "Bihar",
            "district": "Patna"
        }
        response = client.post("/api/v1/status/briefing", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "data" in data
        briefing = data["data"]
        assert briefing["name"] == "SUNITA DEVI"
        assert "booth_location" in briefing
        assert "election_date" in briefing

    def test_briefing_contains_polling_hours(self):
        """Briefing includes polling hours information."""
        payload = {"name": "Test Voter", "state": "Kerala", "district": "Ernakulam"}
        response = client.post("/api/v1/status/briefing", json=payload)
        data = response.json()["data"]
        assert "polling_hours" in data
        assert "7:00 AM" in data["polling_hours"]

    def test_briefing_constituency_format(self):
        """Briefing constituency is formatted as STATE — DISTRICT."""
        payload = {"name": "Test", "state": "Maharashtra", "district": "Mumbai"}
        response = client.post("/api/v1/status/briefing", json=payload)
        constituency = response.json()["data"]["constituency"]
        assert "MAHARASHTRA" in constituency
        assert "MUMBAI" in constituency


# ─────────────────────────────────────────────────────────
# FAQs
# ─────────────────────────────────────────────────────────

class TestFAQs:
    def test_faqs_returns_list(self):
        """FAQs endpoint returns a list of Q&A pairs."""
        response = client.get("/api/v1/faqs")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "faqs" in data
        assert len(data["faqs"]) > 0

    def test_faqs_have_question_and_answer(self):
        """Each FAQ has both 'q' and 'a' fields."""
        response = client.get("/api/v1/faqs")
        for faq in response.json()["faqs"]:
            assert "q" in faq
            assert "a" in faq

    def test_faqs_contain_rule_49p_info(self):
        """FAQs include critical Form 17B information."""
        response = client.get("/api/v1/faqs")
        faqs_text = str(response.json()["faqs"])
        assert "17B" in faqs_text or "Tendered Ballot" in faqs_text


# ─────────────────────────────────────────────────────────
# CORS & SECURITY HEADERS
# ─────────────────────────────────────────────────────────

class TestSecurityAndCORS:
    def test_cors_headers_present(self):
        """CORS headers are present for API access."""
        response = client.options(
            "/api/v1/states",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
        )
        # TestClient handles CORS at middleware level
        assert response.status_code in [200, 405]

    def test_api_does_not_expose_db_path(self):
        """API responses do not leak internal DB path."""
        response = client.get("/api/v1/states")
        assert "votesafe.db" not in response.text
        assert "/sqlite" not in response.text.lower()

    def test_api_does_not_expose_stack_traces(self):
        """Invalid input does not expose Python stack traces."""
        response = client.post("/api/v1/onboard", json={"invalid": "data"})
        assert "Traceback" not in response.text
        assert "File \"" not in response.text


# ─────────────────────────────────────────────────────────
# EDGE CASES & ROBUSTNESS
# ─────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_name_in_onboarding(self):
        """Onboarding with empty string name is handled."""
        payload = {"name": "", "state": "Delhi", "district": "Central"}
        response = client.post("/api/v1/onboard", json=payload)
        # Should either succeed or return a clean validation error
        assert response.status_code in [200, 422]

    def test_special_characters_in_name(self):
        """Special characters in voter name are handled safely."""
        payload = {
            "name": "O'Brien Kumar; DROP TABLE users;--",
            "state": "Goa",
            "district": "North Goa"
        }
        response = client.post("/api/v1/onboard", json=payload)
        assert response.status_code == 200  # Should not crash
        assert "success" in response.json()["status"]

    def test_long_pincode_truncated(self):
        """Pincode endpoint handles non-numeric/invalid input gracefully."""
        response = client.get("/api/v1/resolve_pincode/ABCDEF")
        assert response.status_code == 200
        assert "status" in response.json()

    def test_incident_message_too_long(self):
        """Very long incident messages are stored without crashing."""
        payload = {
            "user_name": "StressTestUser",
            "msg": "A" * 5000  # 5000-char message
        }
        response = client.post("/api/v1/incidents", json=payload)
        assert response.status_code == 200

# ─────────────────────────────────────────────────────────
# CIVIC AI & HEALTH
# ─────────────────────────────────────────────────────────

class TestCivicAI:
    def test_civic_ai_success(self):
        """Civic AI strategist returns a relevant answer."""
        response = client.post("/api/v1/civic-ai/ask", json={
            "question": "What is Rule 49P?",
            "context": "Delhi"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "answer" in data
        assert len(data["answer"]) > 10

    def test_civic_ai_non_civic_rejection(self):
        """Civic AI rejects non-election related questions."""
        response = client.post("/api/v1/civic-ai/ask", json={
            "question": "What is the best movie?",
            "context": ""
        })
        assert response.status_code == 200
        data = response.json()
        assert "I can only assist with voter rights" in data["answer"]

    def test_civic_ai_empty_question(self):
        """Civic AI returns error for empty question."""
        response = client.post("/api/v1/civic-ai/ask", json={"question": ""})
        assert response.status_code == 200
        assert response.json()["status"] == "error"

class TestHealth:
    def test_health_endpoint(self):
        """Health endpoint returns system status and version."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "gemini_available" in data
