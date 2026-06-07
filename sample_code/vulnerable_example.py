"""
Sample Python file with intentional security and quality issues.
Used for demonstrating the multi-agent code review system.
"""
import pickle
import hashlib
import subprocess
import random


# ❌ Hardcoded credentials - critical security issue
password = "admin123"
api_key = "sk-prod-abc123xyz789"
DATABASE_URL = "postgresql://admin:password123@localhost/prod"


def get_user(user_id):
    """Get user from database."""
    # ❌ SQL injection vulnerability
    query = "SELECT * FROM users WHERE id = %s" % user_id
    return query


def authenticate(username, password):
    """Authenticate user."""
    # ❌ Weak hashing algorithm
    hashed = hashlib.md5(password.encode()).hexdigest()
    return hashed == "5f4dcc3b5aa765d61d8327deb882cf99"


def run_system_command(cmd):
    """Run a system command."""
    # ❌ Shell injection risk
    result = subprocess.run(cmd, shell=True, capture_output=True)
    return result.stdout.decode()


def process_user_input(data=[], config={}):
    """Process user input."""
    # ❌ Mutable default arguments
    # ❌ Dangerous eval usage
    try:
        result = eval(data)
        return result
    except:  # ❌ Bare except clause
        pass


def generate_session_token():
    """Generate a session token."""
    # ❌ Insecure random for security token
    return str(random.randint(100000, 999999))


def load_user_session(filepath):
    """Load user session from file."""
    # ❌ Insecure deserialization
    with open(filepath, "rb") as f:
        return pickle.load(f)


def fetch_data(url):
    """Fetch data from URL."""
    import requests
    # ❌ SSL verification disabled
    response = requests.get(url, verify=False)
    return response.json()


# ❌ Debug mode enabled
DEBUG = True
