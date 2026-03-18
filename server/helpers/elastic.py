import os
import httpx
from logger import get_logger

logger = get_logger(__name__)

ES_URL = os.environ.get("ES_URL")
ES_API_KEY = os.environ.get("ES_API_KEY")
ES_INDEX = "scanr-publications"


def es_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if ES_API_KEY:
        headers["Authorization"] = ES_API_KEY
    return headers


def es_search(query: dict) -> dict:
    url = f"{ES_URL}/{ES_INDEX}/_search"
    logger.debug(f"{url=}")
    with httpx.Client() as client:
        response = client.post(url, headers=es_headers(), json=query, timeout=30)
        response.raise_for_status()
        return response.json()
