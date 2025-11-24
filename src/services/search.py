import os, requests
from typing import List, Dict
from dotenv import load_dotenv
from .scrape import normalize_url

load_dotenv()
SEARCH_PROVIDER = os.getenv('SEARCH_PROVIDER', 'serpapi')
SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
GOOGLE_CSE_API_KEY = os.getenv('GOOGLE_CSE_API_KEY')
GOOGLE_CSE_CX = os.getenv('GOOGLE_CSE_CX')

class SearchResult(Dict):
    pass

def serpapi_google_search(query: str, count: int = 10) -> List[SearchResult]:
    if not SERPAPI_API_KEY:
        return []
    endpoint = 'https://serpapi.com/search.json'
    params = { 'engine': 'google', 'q': query, 'num': min(10, count), 'api_key': SERPAPI_API_KEY }
    r = requests.get(endpoint, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    results = []
    for item in data.get('organic_results', []) or []:
        results.append(SearchResult({
            'name': item.get('title'),
            'url': normalize_url(item.get('link')),
            'snippet': item.get('snippet'),
            'displayUrl': item.get('displayed_link') or item.get('link'),
        }))
    return results

def google_cse_search(query: str, count: int = 10) -> List[SearchResult]:
    if not (GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX):
        return []
    endpoint = 'https://www.googleapis.com/customsearch/v1'
    params = { 'q': query, 'key': GOOGLE_CSE_API_KEY, 'cx': GOOGLE_CSE_CX, 'num': min(10, count) }
    r = requests.get(endpoint, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    results = []
    for item in data.get('items', []) or []:
        results.append(SearchResult({
            'name': item.get('title'),
            'url': normalize_url(item.get('link')),
            'snippet': item.get('snippet'),
            'displayUrl': item.get('link'),
        }))
    return results

def web_search(query: str, count: int = 10) -> List[SearchResult]:
    provider = SEARCH_PROVIDER.lower()
    if provider == 'serpapi':
        return serpapi_google_search(query, count)
    elif provider in ('google_cse', 'google'):
        return google_cse_search(query, count)
    else:
        return serpapi_google_search(query, count)
