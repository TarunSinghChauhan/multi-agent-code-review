from src.agents.state import PRState, FixProposal
from src.core.logging import get_logger

logger = get_logger(__name__)

FIX_TEMPLATES = {
    "hardcoded_password": {
        "original": 'password = "admin123"',
        "fixed": 'password = os.environ.get("APP_PASSWORD")',
        "explanation": "Moved password to environment variable using os.environ.get()",
    },
    "hardcoded_api_key": {
        "original": 'api_key = "sk-..."',
        "fixed": 'api_key = os.environ.get("API_KEY")',
        "explanation": "Moved API key to environment variable",
    },
    "eval_usage": {
        "original": "result = eval(data)",
        "fixed": "result = ast.literal_eval(data)  # Safe alternative to eval()",
        "explanation": "Replaced dangerous eval() with safe ast.literal_eval()",
    },
    "shell_injection": {
        "original": 'subprocess.run(cmd, shell=True)',
        "fixed": 'subprocess.run(cmd.split(), shell=False)',
        "explanation": "Disabled shell=True to prevent shell injection attacks",
    },
    "bare_except": {
        "original": "except:",
        "fixed": "except Exception as e:",
        "explanation": "Replaced bare except with specific exception handler",
    },
    "mutable_default_arg": {
        "original": "def process_data(data=[], config={}):",
        "fixed": "def process_data(data=None, config=None):\n    data = data or []\n    config = config or {}",
        "explanation": "Replaced mutable default arguments with None and initialized inside function",
    },
    "weak_hash": {
        "original": "hashlib.md5(pwd.encode()).hexdigest()",
        "fixed": "hashlib.sha256(pwd.encode()).hexdigest()",
        "explanation": "Replaced weak MD5 with SHA-256",
    },
    "insecure_random": {
        "original": "random.randint(100000, 999999)",
        "fixed": "secrets.randbelow(900000) + 100000",
        "explanation": "Replaced insecure random with cryptographically secure secrets module",
    },
    "insecure_deserialization": {
        "original": "pickle.load(f)",
        "fixed": "json.load(f)  # Use JSON instead of pickle",
        "explanation": "Replaced insecure pickle with safe JSON deserialization",
    },
    "ssl_verification_disabled": {
        "original": "requests.get(url, verify=False)",
        "fixed": "requests.get(url, verify=True)",
        "explanation": "Enabled SSL verification to prevent MITM attacks",
    },
    "debug_mode": {
        "original": "DEBUG = True",
        "fixed": 'DEBUG = os.environ.get("DEBUG", "False").lower() == "true"',
        "explanation": "Moved DEBUG flag to environment variable",
    },
}


async def fix_proposal_agent(state: PRState) -> dict:
    """Agent 3: Fix Proposal Generator — zero API cost using templates."""
    logger.info("fix_proposal_agent_started", job_id=state["job_id"])
    proposals: list[FixProposal] = []

    critical_high = [
        i for i in state["issues"]
        if i.severity in ("critical", "high")
    ][:5]

    seen_types = set()
    for issue in critical_high:
        if issue.issue_type in FIX_TEMPLATES and issue.issue_type not in seen_types:
            template = FIX_TEMPLATES[issue.issue_type]
            proposals.append(FixProposal(
                issue_title=issue.title,
                original_code=template["original"],
                fixed_code=template["fixed"],
                explanation=template["explanation"],
            ))
            seen_types.add(issue.issue_type)

    logger.info("fix_proposal_agent_done", job_id=state["job_id"], proposals=len(proposals))
    return {"fix_proposals": proposals, "total_cost_usd": state["total_cost_usd"]}