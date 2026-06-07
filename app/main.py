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
import certifi

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

# Pydantic models for external API responses
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

# Helper Functions
async def get_directus_data(client_httpx: httpx.AsyncClient, domain: str, id: str):
    directus_token = global_tokens.get(domain)
    if not directus_token:
        raise HTTPException(status_code=404, detail="Token not found for the given domain.")

    api_url = f"https://{domain}/items/idols/{id}" if domain == "tcreator.cloud" else f"https://{domain}/items/channels/{id}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {directus_token}"
    }

    try:
        response = await client_httpx.get(api_url, headers=headers)
        response.raise_for_status()
        return response.json().get("data", {})
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error calling Directus API: {e}")

async def ayrshare_delete_profile(client_httpx: httpx.AsyncClient, profile_key: str):
    headers = {
        'Authorization': f"Bearer {AYRSHARE_API_KEY}",
        'Content-Type': 'application/json',
        'Profile-Key': profile_key
    }
    try:
        response = await client_httpx.delete("https://app.ayrshare.com/api/profiles/profile", headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error deleting Ayrshare profile: {e}")

async def ayrshare_delete_network(client_httpx: httpx.AsyncClient, profile_key: str, platform: str):
    headers = {
        'Authorization': f"Bearer {AYRSHARE_API_KEY}",
        'Content-Type': 'application/json',
        'Profile-Key': profile_key
    }
    payload = {'platform': platform}
    try:
        response = await client_httpx.request(
            "DELETE",
            "https://app.ayrshare.com/api/profiles/profile",
            headers=headers,
            json=payload
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error deleting Ayrshare network: {e}")

async def ayrshare_create_profile(client_httpx: httpx.AsyncClient, profile_title: str):
    headers = {
        "Authorization": f"Bearer {AYRSHARE_API_KEY}",
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    payload = {"title": profile_title}
    try:
        response = await client_httpx.post("https://app.ayrshare.com/api/profiles/profile", data=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error creating Ayrshare profile: {e}")

async def ayrshare_generate_jwt(client_httpx: httpx.AsyncClient, profile_key: str):
    jwt_payload = f'domain=id-oqsv9&privateKey=-----BEGIN%20RSA%20PRIVATE%20KEY-----%0AMIIEowIBAAKCAQEA8T9eeYVkoWY8HEPZX%2BhcIxVxFzMSrKgV8XlaSG6ov6l2pRiv%0A8iYZ3hflwe10ASm%2B5NUsVsD3%2BstuYjIbnhCawXs%2B6VfLV8myn8y%2B0DiGGExoHkLQ%0AMgyIgzdJjEuoDdUf10ED8tFT6i3vdOp%2BonuH7c%2BHTT6KdtZEYOEQbVB%2BnOQvGk2C%0AcCCi%2FFxUUwcLyLwgJRo8Mu4ObTX8nIi2fRpgMOMJT5J3TVa%2BqUGakubutB7asZ0%2F%0AMOjnsU1bSlH2SmkxY2fJzYfvDf4J3BxyMB8qG2mnKAtH0SQFgQ3wLQArff2dn465%0AGLV9aWHeluFQDOrt9llVobcyFUKDMlp9ok1FVwIDAQABAoIBAC8mM%2BgrLmou6XOa%0AvRq19n%2Fy2lnu5Ojypus9TOxYGEnxLFuC8iwwzyBtaj2XE3OAvarKkPJZn32YEbhG%0AU8h2NVC4Lij7vCWpqWv635YhXe%2FUywqTA06szWdbwFeXl74wV5tBvSxRRgXAOYsP%0Ao3VNEFlllGt%2F3B7yrIWEpym%2BMCioPPK%2FifcV6wcL4r6%2F1EBCux4KPlx94TvjOJ36%0ALd3Aax5WLnpaAI6TnTEZYEEwEz9pw%2FnmgFOjwwGLPBucWcYXOEIq2fZxrdsGB7UC%0Ai8AtRESDDzqGJBp6qm7IKqiWatDBuaNn3%2BaIsNvmwlMRJBgrxcy0FV%2Ft80PJ3LM1%0ArsvG5PUCgYEA%2Fs8MtxEC1FsbuIzHeUi6eMoRdNKmghU3TrHuNRmr6ZioVUb72FPA%0A7v8tp64jZVeM8qsj%2FwH1FRjemZIalZuLGktTGJgR8%2F0JTb0e4LvRARn41InBj0df%0AGEZX1unG1wNSOs3%2Blh7haXWFQi407mB%2FMbbfrkerheYGCmCUGtFVAUsCgYEA8mAW%0A6v%2BAlEyhW8EUjQMKMMTYyFxY5vVNII5rOE7t7mPWjbA3qnc6dNxDY%2BW04zjflkQp%0AwktP1CDY5KjTzlyFuM8WTG4KWzA3r48ARWucWXAZxpWqkvDTTxNONXgB44VNNe0B%0AKlpSkOryAJNqaYCIW19tI%2FVvl6S0pwHgFrzUUKUCgYEAioeqlASNk0INKiJveELQ%0ADkddgjPcDrDWJtSZewj%2F67nxGpvC4%2FN02vqkqZsE513X5T6iDUvVIKkqrDdAeMHd%0AuGfnP2G9sPaKjlcZaHjzwjOKkpJqRyk4TAxCSTdDwTWvCQVhOeCEED%2ByOS7B3C9e%0AN3sC1M9mMx%2FBfPbQzlusaU0CgYAeIy6WV%2BDQD9s8gnygsBETUVa3SyxOw4%2Bsjajt%0AXnsdWlKyWYgCbULahwzmHgjo%2FAhpMd6TZzPs54ywmgGENmL2QOG%2F7SrifdNexAQ%0AnYraYCMEW1XTYZiUy4y8%2F0gU111raCXt8z8y%2F9PJmIrxxWavHeV%2FRCR1EajY31XS%0A3fX0dQKBgBqE2iMfMnImPvdE31x6tRq14NOrwW3pCj1haWqk19Z3sabCM2LWzuEj%0AeoDmX6CVHHN2E5N%2FVZc%2B%2BQbGyOUsJBhUF4Okhaae%2BE0rhEtH7%2BMJJlf1H%2BjlUTAo%0ApvrFxVCUqXlm39Fn79h4FMEsitHodP8Ng2ZCN5UIdWUM7bV7%2Ftp%2F%0A-----END%20RSA%20PRIVATE%20KEY-----%0A&profileKey={profile_key}&logout=True&'
    headers = {
        'Authorization': f'Bearer {AYRSHARE_API_KEY}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    try:
        response = await client_httpx.post("https://app.ayrshare.com/api/profiles/generateJWT", data=jwt_payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error generating JWT: {e}")

# API Endpoints
@app.get("/delete-profile/{domain}/{id}")
async def delete_profile(
    domain: str = Path(..., description="The domain to fetch channels from"),
    id: str = Path(..., description="The channel ID"),
):
    async with httpx.AsyncClient(verify=certifi.where(), timeout=60.0) as client_httpx:
        # Step 1: Fetch data from directus
        directus_data = await get_directus_data(client_httpx, domain, id)
        ayrshare_key = directus_data.get("key")
        ayrshare_profile = directus_data.get("profile")

        if not ayrshare_key:
            raise HTTPException(status_code=400, detail="Profile key not found in Directus.")

        # Step 2: call ayrshare delete profile
        await ayrshare_delete_profile(client_httpx, ayrshare_key)

        # Step 3: update used = false and reset fields in mongodb
        try:
            run_blocking(
                profiles_collection.find_one_and_update,
                {"profile": ayrshare_profile, "domain": domain},
                {"$set": {
                    "used": False,
                    "profileKey": None,
                    "refId": None,
                    "networks": {
                        "tiktok": False,
                        "short": False
                    }
                }},
                upsert=True
            )
        except PyMongoError as e:
            raise HTTPException(status_code=500, detail=f"Error updating profiles in MongoDB: {e}")

        return {"status": "success", "message": "Profile deleted successfully"}

@app.get("/delete-network/{domain}/{id}")
async def delete_network(
    domain: str = Path(..., description="The domain to fetch channels from"),
    id: str = Path(..., description="The channel ID"),
):
    async with httpx.AsyncClient(verify=certifi.where(), timeout=60.0) as client_httpx:
        # Step 1: Fetch data from Directus
        directus_data = await get_directus_data(client_httpx, domain, id)
        ayrshare_key = directus_data.get("key")
        ayrshare_profile = directus_data.get("profile")
        platform = directus_data.get("network")

        if not platform:
            raise HTTPException(status_code=400, detail="Platform not found in Directus data.")

        # Step 2: Delete network from Ayrshare profile
        await ayrshare_delete_network(client_httpx, ayrshare_key, platform)

        # Step 3: Update MongoDB networks to False
        try:
            run_blocking(
                profiles_collection.find_one_and_update,
                {"profile": ayrshare_profile, "domain": domain},
                {"$set": {f"networks.{platform}": False}},
                upsert=True
            )
        except PyMongoError as e:
            raise HTTPException(status_code=500, detail=f"MongoDB update failed: {e}")

        return {"status": "success", "message": f"{platform} network deleted"}

@app.get("/profile/{domain}/{id}/{network}")
async def get_profile_endpoint(
    domain: str = Path(..., description="The domain to fetch channels from"),
    id: str = Path(..., description="The channel ID"),
    network: str = Path(..., description="The network (e.g. tiktok, short)"),
):
    async with httpx.AsyncClient(verify=certifi.where(), timeout=60.0) as client_httpx:
        # Step 1: Fetch an unused network profile from MongoDB
        try:
            query = {f"networks.{network}": False, "domain": domain}
            profile_doc_future = run_blocking(profiles_collection.find_one, query)
            profile_doc = profile_doc_future.result()
            print(profile_doc)
            if not profile_doc:
                raise HTTPException(status_code=404, detail=f"No profiles available for {network}.")
            profile = profile_doc.get("profile")
            profileKey = profile_doc.get("profileKey")
        except PyMongoError as e:
            raise HTTPException(status_code=500, detail=f"MongoDB query failed: {e}")

        # Step 2: If profileKey is not present, call Ayrshare profile API to create a new profile
        if not profileKey:
            profile_data = await ayrshare_create_profile(client_httpx, profile)
            if profile_data.get("status") != "success":
                raise HTTPException(status_code=400, detail="Ayrshare profile creation failed.")

            profileKey = profile_data.get("profileKey")
            refId = profile_data.get("refId")

            # Update MongoDB with newly created profile details
            try:
                run_blocking(
                    profiles_collection.find_one_and_update,
                    {"profile": profile, "domain": domain},
                    {"$set": {
                        f"networks.{network}": True,
                        "profileKey": profileKey,
                        "refId": refId,
                        "used": True
                    }},
                )
            except PyMongoError as e:
                raise HTTPException(status_code=500, detail=f"MongoDB update failed: {e}")
        else:
            # If already has profileKey, just update network status and used state
            try:
                run_blocking(
                    profiles_collection.find_one_and_update,
                    {"profile": profile, "domain": domain},
                    {"$set": {
                        f"networks.{network}": True,
                        "used": True
                    }},
                )
            except PyMongoError as e:
                raise HTTPException(status_code=500, detail=f"MongoDB update failed: {e}")

        # Step 3: Call Directus API to update key and profile info
        directus_token = global_tokens.get(domain)
        if not directus_token:
            raise HTTPException(status_code=404, detail="Token not found for the given domain.")
        
        api_url = f"https://{domain}/items/idols/{id}" if domain == "tcreator.cloud" else f"https://{domain}/items/channels/{id}"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {directus_token}"
        }
        payload = json.dumps({
            "key": profileKey,
            "profile": profile
        })

        try:
            response = await client_httpx.patch(api_url, data=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=f"Directus update failed: {e}")

        # Step 4: Generate JWT URL
        jwt_data = await ayrshare_generate_jwt(client_httpx, profileKey)
        if jwt_data.get("status") != "success":
            raise HTTPException(status_code=400, detail="JWT generation failed.")

        # Step 5: Redirect to the JWT URL
        return RedirectResponse(url=jwt_data.get("url"), status_code=301)
