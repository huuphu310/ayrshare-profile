import os
from fastapi import FastAPI, HTTPException, Path, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError
import httpx
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import json

# Load environment variables
load_dotenv()

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
AYRSHARE_API_KEY = os.getenv("AYRSHARE_API_KEY", "your_api_key_here")
DATABASE_NAME = os.getenv("DATABASE_NAME", "your_database_name")

app = FastAPI()

# MongoDB Client
client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]
profiles_collection = db["profiles"]
directus_token_collection = db["directus_token"]

# ThreadPoolExecutor
executor = ThreadPoolExecutor(max_workers=10)

# Global token cache
global_tokens = {}


# Pydantic Models
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


# Helper Functions
async def get_directus_data(client_httpx: httpx.AsyncClient, domain: str, id: str):
    directus_token = global_tokens.get(domain)
    if not directus_token:
        raise HTTPException(status_code=404, detail="Token not found for the given domain.")

    api_url = f"https://{domain}/items/idols/{id}" if domain == "tcreator.cloud" else f"https://{domain}/items/channels/{id}"
    headers = {'Authorization': f"Bearer {directus_token}"}

    try:
        response = await client_httpx.get(api_url, headers=headers)
        response.raise_for_status()
        return response.json().get("data", {})
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error calling Directus API: {e}")


async def ayrshare_delete_profile(client_httpx: httpx.AsyncClient, profile_key: str):
    headers = {'Authorization': f"Bearer {AYRSHARE_API_KEY}", 'Profile-Key': profile_key}
    try:
        response = await client_httpx.delete("https://app.ayrshare.com/api/profiles/profile", headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error deleting Ayrshare profile: {e}")


async def ayrshare_delete_network(client_httpx: httpx.AsyncClient, profile_key: str, platform: str):
    headers = {'Authorization': f"Bearer {AYRSHARE_API_KEY}", 'Profile-Key': profile_key}
    payload = {'platform': platform}
    try:
        response = await client_httpx.delete("https://app.ayrshare.com/api/profiles/profile", headers=headers,
                                             json=payload)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error deleting Ayrshare network: {e}")


async def ayrshare_create_profile(client_httpx: httpx.AsyncClient, profile_title: str):
    headers = {"Authorization": f"Bearer {AYRSHARE_API_KEY}", 'Content-Type': 'application/x-www-form-urlencoded'}
    payload = {"title": profile_title}
    try:
        response = await client_httpx.post("https://app.ayrshare.com/api/profiles/profile", data=payload,
                                           headers=headers)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error creating Ayrshare profile: {e}")


async def ayrshare_generate_jwt(client_httpx: httpx.AsyncClient, profile_key: str):
    jwt_payload = f'domain=id-oqsv9&privateKey=...&profileKey={profile_key}&logout=True'  # Replace with your private key
    headers = {'Authorization': f'Bearer {AYRSHARE_API_KEY}', 'Content-Type': 'application/x-www-form-urlencoded'}
    try:
        response = await client_httpx.post("https://app.ayrshare.com/api/profiles/generateJWT", data=jwt_payload,
                                           headers=headers)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error generating JWT: {e}")


def run_blocking(func, *args, **kwargs):
    return executor.submit(func, *args, **kwargs)


@app.on_event("startup")
def startup_event():
    try:
        tokens = directus_token_collection.find({})
        for token in tokens:
            global_tokens[token.get("domain")] = token.get("token")
    except PyMongoError as e:
        print(f"Error fetching tokens at startup: {e}")


@app.on_event("shutdown")
def shutdown_event():
    executor.shutdown(wait=True)
    client.close()


# API Endpoints
@app.get("/delete-profile/{domain}/{id}")
async def delete_profile_endpoint(domain: str, id: str):
    async with httpx.AsyncClient() as client_httpx:
        directus_data = await get_directus_data(client_httpx, domain, id)
        ayrshare_key = directus_data.get("key")
        ayrshare_profile = directus_data.get("profile")

        await ayrshare_delete_profile(client_httpx, ayrshare_key)

        try:
            run_blocking(
                profiles_collection.find_one_and_update,
                {"profile": ayrshare_profile, "domain": domain},
                {"$set": {"used": False}},
                upsert=True
            )
        except PyMongoError as e:
            raise HTTPException(status_code=500, detail=f"MongoDB update failed: {e}")

        return {"status": "success", "message": "Profile deleted successfully"}


@app.get("/delete-network/{domain}/{id}")
async def delete_network_endpoint(domain: str, id: str):
    async with httpx.AsyncClient() as client_httpx:
        directus_data = await get_directus_data(client_httpx, domain, id)
        ayrshare_key = directus_data.get("key")
        ayrshare_profile = directus_data.get("profile")
        platform = directus_data.get("network")

        if not platform:
            raise HTTPException(status_code=400, detail="Platform not found in Directus data.")

        await ayrshare_delete_network(client_httpx, ayrshare_key, platform)

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
async def get_profile_endpoint(domain: str, id: str, network: str):
    try:
        query = {f"networks.{network}": False, "domain": domain}
        profile_doc = await run_blocking(profiles_collection.find_one, query)
        if not profile_doc:
            raise HTTPException(status_code=404, detail=f"No profiles available for {network}.")
        profile = profile_doc.get("profile")
        used = profile_doc.get("used", False)
        profileKey = profile_doc.get("profileKey")

    except PyMongoError as e:
        raise HTTPException(status_code=500, detail=f"MongoDB query failed: {e}")

    async with httpx.AsyncClient() as client_httpx:
        if not used:
            profile_data = await ayrshare_create_profile(client_httpx, profile)
            if profile_data.get("status") != "success":
                raise HTTPException(status_code=400, detail="Ayrshare profile creation failed.")

            profileKey = profile_data.get("profileKey")
            refId = profile_data.get("refId")

            try:
                run_blocking(
                    profiles_collection.find_one_and_update,
                    {"profile": profile},
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
            # If already used, just update the network status
            try:
                run_blocking(
                    profiles_collection.find_one_and_update,
                    {"profile": profile},
                    {"$set": {f"networks.{network}": True}},
                )
            except PyMongoError as e:
                raise HTTPException(status_code=500, detail=f"MongoDB update failed: {e}")

        directus_token = global_tokens.get(domain)
        api_url = f"https://{domain}/items/idols/{id}" if domain == "tcreator.cloud" else f"https://{domain}/items/channels/{id}"
        headers = {'Content-Type': 'application/json', 'Authorization': f"Bearer {directus_token}"}
        payload = json.dumps({"key": profileKey, "profile": profile})

        try:
            await client_httpx.patch(api_url, data=payload, headers=headers)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=f"Directus update failed: {e}")

        jwt_data = await ayrshare_generate_jwt(client_httpx, profileKey)
        if jwt_data.get("status") != "success":
            raise HTTPException(status_code=400, detail="JWT generation failed.")

        return RedirectResponse(url=jwt_data.get("url"), status_code=301)
