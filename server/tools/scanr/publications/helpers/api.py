import os
import requests


def request_scanr_publications(payload: dict) -> dict:
    """Request ScanR publications API"""
    response = requests.get(
        "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
        json=payload,
        headers={"Authorization": os.getenv("SCANR_API_KEY")},
    )
    response.raise_for_status()
    return response.json()


def scanr_publication_to_string(publication: dict):
    """Format ScanR publication to string"""
    contents = [f"Title: {publication['title']['default']}", f"  ID: {publication['id']}"]
    if publication.get("summary"):
        summary = (
            publication["summary"].get("default") or publication["summary"].get("en") or publication["summary"].get("fr")
        )
        if summary:
            contents.append(f"  Summary: {summary}")
    if publication.get("authors"):
        contents.append(
            f"  Authors: {', '.join([author['fullName'] for author in publication['authors'] if author.get("fullName")])}"
        )
    if publication.get("domains"):
        contents.append(
            f"  Topics: {', '.join([domain['label']['default'] for domain in publication['domains'] if domain.get("label", {}).get("default")])}"
        )
    if publication.get("isOa"):
        contents.append(f"  Open access: {publication['isOa']}")
    if publication.get("type"):
        contents.append(f"  Type: {publication['type']}")
    if publication.get("year"):
        contents.append(f"  Year: {publication['year']}")
    if publication.get("projects"):
        contents.append(
            f"  Projects: {', '.join([project['id'] for project in publication['projects'] if project.get('id')])}"
        )
    if publication.get("software"):
        contents.append(
            f"  Software: {', '.join([software['softwareName'] for software in publication['software'] if software.get('softwareName')])}"
        )
    return "\n".join(contents)
