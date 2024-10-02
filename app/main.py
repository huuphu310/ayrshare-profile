import os
from fastapi import FastAPI, HTTPException, Path, Depends, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError
import httpx
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import json
# Load environment variables from .env file
load_dotenv()

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
AYRSHARE_API_KEY = os.getenv("AYRSHARE_API_KEY", "your_api_key_here")  # Replace with your actual API key
DATABASE_NAME = os.getenv("DATABASE_NAME", "your_database_name")
DIRECTUS_AUTH_TOKEN = os.getenv("DIRECTUS_AUTH_TOKEN", "your_directus_auth_token_here")  # Replace with your actual token

app = FastAPI()

# Initialize MongoDB client
client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]
channels_collection = db["channels"]
profiles_collection = db["profiles"]
directus_token_collection = db["directus_token"]

# Initialize ThreadPoolExecutor for handling synchronous DB operations
executor = ThreadPoolExecutor(max_workers=10)


global_tokens = {}

# Function to load tokens into global variable
def load_tokens():
    global global_tokens
    try:
        tokens = directus_token_collection.find({})
        for token in tokens:
            domain = token.get("domain")
            token_value = token.get("token")
            if domain and token_value:
                global_tokens[domain] = token_value
    except PyMongoError as e:
        print(f"An error occurred while fetching tokens: {e}")

# Load tokens at startup
load_tokens()
# Pydantic models for external API responses (assuming structure)
class ProfileData(BaseModel):
    profile: str
    profileKey: str
    refId: str
    domain: str

class ProfileResponse(BaseModel):
    status: str
    data: ProfileData

class ChannelsData(BaseModel):
    profileKey: Optional[str]
    profile: Optional[str]

class ChannelsResponse(BaseModel):
    # Define fields based on actual API response
    # Example:
    profileKey: Optional[str]
    profile: Optional[str]

class GenerateJWTResponse(BaseModel):
    status: str
    url: str

# Dependency to run blocking code in thread pool
def run_blocking(func, *args, **kwargs):
    return executor.submit(func, *args, **kwargs)

@app.on_event("shutdown")
def shutdown_event():
    executor.shutdown(wait=True)

@app.get("/profile/{domain}/{id}")
async def handle_profile(
    domain: str = Path(..., description="The domain to fetch channels from"),
    id: str = Path(..., description="The channel ID"),
):
    async with httpx.AsyncClient() as client_httpx:
        # Step 1: Fetch an unused profile from MongoDB
        try:
            # Atomically find one document with used=False and set used=True
            profile_doc_future = run_blocking(
                profiles_collection.find_one,
                {"used": False, "domain": domain}
            )
            profile_doc = profile_doc_future.result()
            print(profile_doc)
            if not profile_doc:
                raise HTTPException(status_code=404, detail="No unused profiles available.")

            profile = profile_doc.get("profile")
            print(profile)
            if not profile:
                raise HTTPException(status_code=500, detail="Selected profile is missing.")
        except PyMongoError as e:
            raise HTTPException(status_code=500, detail=f"Error fetching profile from MongoDB: {e}")

        # Step 2: Call Ayrshare profile API with the fetched profile
        profile_api_url = "https://app.ayrshare.com/api/profiles/profile"
        profile_payload = {
            "title": profile  # Using the fetched profile
        }
        headers = {
            "Authorization": f"Bearer {AYRSHARE_API_KEY}",
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        try:
            profile_response = await client_httpx.post(profile_api_url, data=profile_payload, headers=headers)
            profile_response.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=f"Error calling Ayrshare profile API: {e}")

        profile_data = profile_response.json()

        if profile_data.get("status") != "success":
            raise HTTPException(status_code=400, detail="Ayrshare profile API returned unsuccessful status.")

        # Extract required fields
        if profile_data.get("status") == "success":
            profileKey = profile_data.get("profileKey")
            refId = profile_data.get("refId")

        if not all([profileKey, refId]):
            raise HTTPException(status_code=400, detail="Missing required profile data.")

        # Step 3: Update 'profiles' collection with 'refId' and 'profileKey'
        try:
            profile_doc_future = run_blocking(
                profiles_collection.find_one_and_update,
                {"profile": profile},
                {"$set": {"used": True, "profileKey": profileKey, "refId": refId}},
                return_document=ReturnDocument.AFTER
            )
        except PyMongoError as e:
            raise HTTPException(status_code=500, detail=f"Error updating profiles in MongoDB: {e}")

        # Step 3: Call the domain-specific channels API
        directus_token = global_tokens.get(domain)
        if not directus_token:
            raise HTTPException(status_code=404, detail="Token not found for the given domain.")

        channels_api_url = f"https://{domain}/items/channels/{id}"
        payload = json.dumps({
            "key": profileKey,
            "profile": profile
        })

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {directus_token}"
        }
        try:
            channels_response = await client_httpx.patch(channels_api_url, data=payload, headers=headers)
            channels_response.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=f"Error calling channels API: {e}")

        # Step 4: If profileKey exists, generate JWT URL
        if profileKey:
            generate_jwt_url = "https://app.ayrshare.com/api/profiles/generateJWT"
            jwt_payload = f'domain=id-oqsv9&privateKey=-----BEGIN%20RSA%20PRIVATE%20KEY-----%0AMIIEowIBAAKCAQEA8T9eeYVkoWY8HEPZX%2BhcIxVxFzMSrKgV8XlaSG6ov6l2pRiv%0A8iYZ3hflwe10ASm%2B5NUsVsD3%2BstuYjIbnhCawXs%2B6VfLV8myn8y%2B0DiGGExoHkLQ%0AMgyIgzdJjEuoDdUf10ED8tFT6i3vdOp%2BonuH7c%2BHTT6KdtZEYOEQbVB%2BnOQvGk2C%0AcCCi%2FFxUUwcLyLwgJRo8Mu4ObTX8nIi2fRpgMOMJT5J3TVa%2BqUGakubutB7asZ0%2F%0AMOjnsU1bSlH2SmkxY2fJzYfvDf4J3BxyMB8qG2mnKAtH0SQFgQ3wLQArff2dn465%0AGLV9aWHeluFQDOrt9llVobcyFUKDMlp9ok1FVwIDAQABAoIBAC8mM%2BgrLmou6XOa%0AvRq19n%2Fy2lnu5Ojypus9TOxYGEnxLFuC8iwwzyBtaj2XE3OAvarKkPJZn32YEbhG%0AU8h2NVC4Lij7vCWpqWv635YhXe%2FUywqTA06szWdbwFeXl74wV5tBvSxRRgXAOYsP%0Ao3VNEFlllGt%2F3B7yrIWEpym%2BMCioPPK%2FifcV6wcL4r6%2F1EBCux4KPlx94TvjOJ36%0ALd3Aax5WLnpaAI6TnTEZYEEwEz9pw%2FnmgFOjwwGLPBucWcYXOEIq2fZxrdsGB7UC%0Ai8AtRESDDzqGJBp6qm7IKqiWatDBuaNn3%2BaIsNvmwlMRJBgrxcy0FV%2Ft80PJ3LM1%0ArsvG5PUCgYEA%2Fs8MtxEC1FsbuIzHeUi6eMoRdNKmghU3TrHuNRmr6ZioVUb72FPA%0A7v8tp64jZVeM8qsj%2FwH1FRjemZIalZuLGktTGJgR8%2F0JTb0e4LvRARn41InBj0df%0AGEZX1unG1wNSOs3%2Blh7haXWFQi407mB%2FMbbfrkerheYGCmCUGtFVAUsCgYEA8mAW%0A6v%2BAlEyhW8EUjQMKMMTYyFxY5vVNII5rOE7t7mPWjbA3qnc6dNxDY%2BW04zjflkQp%0AwktP1CDY5KjTzlyFuM8WTG4KWzA3r48ARWucWXAZxpWqkvDTTxNONXgB44VNNe0B%0AKlpSkOryAJNqaYCIW19tI%2FVvl6S0pwHgFrzUUKUCgYEAioeqlASNk0INKiJveELQ%0ADkddgjPcDrDWJtSZewj%2F67nxGpvC4%2FN02vqkqZsE513X5T6iDUvVIKkqrDdAeMHd%0AuGfnP2G9sPaKjlcZaHjzwjOKkpJqRyk4TAxCSTdDwTWvCQVhOeCEED%2ByOS7B3C9e%0AN3sC1M9mMx%2FBfPbQzlusaU0CgYAeIy6WV%2BDQD9s8gnygsBETUVa3SyxOw4%2Bsjajt%0AXnsdWlKyWYgCbULahwzmHgjo%2FAhpMd6TZzPs54ywmgGENmL2QOG%2F7SrifdNexAQ%2F%0AnYraYCMEW1XTYZiUy4y8%2F0gU111raCXt8z8y%2F9PJmIrxxWavHeV%2FRCR1EajY31XS%0A3fX0dQKBgBqE2iMfMnImPvdE31x6tRq14NOrwW3pCj1haWqk19Z3sabCM2LWzuEj%0AeoDmX6CVHHN2E5N%2FVZc%2B%2BQbGyOUsJBhUF4Okhaae%2BE0rhEtH7%2BMJJlf1H%2BjlUTAo%0ApvrFxVCUqXlm39Fn79h4FMEsitHodP8Ng2ZCN5UIdWUM7bV7%2Ftp%2F%0A-----END%20RSA%20PRIVATE%20KEY-----%0A&profileKey={profileKey}&logout=True&'
            headers = {
                'Authorization': f'Bearer {AYRSHARE_API_KEY}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            try:
                jwt_response = await client_httpx.post(generate_jwt_url, data=jwt_payload, headers=headers)
                jwt_response.raise_for_status()
                print(jwt_response.json())
            except httpx.HTTPError as e:
                raise HTTPException(status_code=500, detail=f"Error calling generateJWT API: {e}")

            jwt_data = jwt_response.json()

            if jwt_data.get("status") != "success":
                raise HTTPException(status_code=400, detail="Ayrshare generateJWT API returned unsuccessful status.")

            url = jwt_data.get("url")
            if not url:
                raise HTTPException(status_code=500, detail="JWT URL not found in response.")

            # Return 301 redirect to the URL
            return RedirectResponse(url=url, status_code=301)

        # If no profileKey, return the profileKey and profile
        return {"profileKey": profileKey, "profile": profile}