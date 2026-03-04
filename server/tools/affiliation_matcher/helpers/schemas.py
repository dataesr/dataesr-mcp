from pydantic import BaseModel, Field


class EnrichedResults(BaseModel):
    id: str = Field(description="matched id in the reference system")
    name: list[str] = Field(description="names of the matched affiliation")
    acronyms: list[str] | None = Field(description="acronyms of the matched affiliation", default=None)
    countries: list[str] | None = Field(description="countries of the matched affiliation", default=None)
    cities: list[str] | None = Field(description="cities of the matched affiliation", default=None)


class AffiliationMatch(BaseModel):
    results: list[str] = Field(description="matched ids in the reference system")
    enriched_results: list[EnrichedResults] | None = Field(
        description="additionnal information for the matched ids", default=None
    )
