import os, requests
from typing import List, Dict

CLIENT_ID = os.getenv('LINKEDIN_CLIENT_ID')
CLIENT_SECRET = os.getenv('LINKEDIN_CLIENT_SECRET')
REDIRECT_URI = os.getenv('LINKEDIN_REDIRECT_URI')

TOKEN_URL = 'https://www.linkedin.com/oauth/v2/accessToken'
API_BASE = 'https://api.linkedin.com/v2'

def exchange_code_for_token(code: str) -> Dict:
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
    }
    r = requests.post(TOKEN_URL, data=data)
    r.raise_for_status()
    return r.json()

def get_company_updates(org_urn: str, access_token: str) -> List[Dict]:
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{API_BASE}/organizationalEntityShareStatistics?q=organizationalEntity&organizationalEntity={org_urn}"
    r = requests.get(url, headers=headers)
    return r.json().get('elements', []) if r.status_code == 200 else []

def get_job_posts(company_name: str, access_token: str) -> List[Dict]:
    return []
