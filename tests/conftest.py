import pytest
import os
import sqlite3
import shutil

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Sets up a clean test database for the entire test session."""
    test_db = "votesafe_test.db"
    # Ensure any old test DB is removed
    if os.path.exists(test_db):
        os.remove(test_db)
    
    # Create the test DB and schema
    conn = sqlite3.connect(test_db)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT, state TEXT, district TEXT, pincode TEXT, epic TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS incidents
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_name TEXT, type TEXT, message TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()
    
    # Tell the app to use the test DB
    os.environ["DATABASE_URL"] = test_db
    
    yield
    
    # Cleanup after session
    if os.path.exists(test_db):
        os.remove(test_db)

@pytest.fixture(autouse=True)
def clean_db_tables():
    """Cleans DB tables before each individual test to ensure isolation."""
    test_db = os.environ.get("DATABASE_URL", "votesafe.db")
    conn = sqlite3.connect(test_db)
    c = conn.cursor()
    c.execute("DELETE FROM users")
    c.execute("DELETE FROM incidents")
    conn.commit()
    conn.close()
    yield
