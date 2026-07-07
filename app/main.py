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

# Map internal network names (used in MongoDB/Directus) to Ayrshare platform names.
# e.g. "short" is our label for YouTube Shorts, but Ayrshare expects "youtube".
# Used by the LEGACY endpoints that operate on the `idols`/`channels` collections.
NETWORK_TO_AYRSHARE = {
    "short": "youtube",
}

# --- New "destinations" collection (multi-source/dest redesign) -------------
# In the redesign, the `idols` collection is superseded by `destinations`.
# Field mapping:  idols.key -> destinations.account_key,
#                 idols.network -> destinations.platform,
#                 idols.profile/app_id -> destinations.profile/app_id.
# Unlike `idols.network`, `destinations.platform` already holds the Ayrshare-native
# name (tiktok/youtube/facebook/douyin) so NO translation is needed for Ayrshare calls.
# The MongoDB profile pool, however, still tracks slots under the legacy keys
# tiktok/short, so we map the platform back to the pool's network key.
PLATFORM_TO_POOL_NETWORK = {
    "youtube": "short",
}

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

async def update_directus_data(client_httpx: httpx.AsyncClient, domain: str, id: str, fields: dict):
    directus_token = global_tokens.get(domain)
    if not directus_token:
        raise HTTPException(status_code=404, detail="Token not found for the given domain.")

    api_url = f"https://{domain}/items/idols/{id}" if domain == "tcreator.cloud" else f"https://{domain}/items/channels/{id}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {directus_token}"
    }

    try:
        response = await client_httpx.patch(api_url, json=fields, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error updating Directus API: {e}")

async def get_destination_data(client_httpx: httpx.AsyncClient, domain: str, id: str):
    """Fetch a row from the new `destinations` collection (multi-source/dest redesign)."""
    directus_token = global_tokens.get(domain)
    if not directus_token:
        raise HTTPException(status_code=404, detail="Token not found for the given domain.")

    api_url = f"https://{domain}/items/destinations/{id}"
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

async def update_destination_data(client_httpx: httpx.AsyncClient, domain: str, id: str, fields: dict):
    """Patch a row in the new `destinations` collection."""
    directus_token = global_tokens.get(domain)
    if not directus_token:
        raise HTTPException(status_code=404, detail="Token not found for the given domain.")

    api_url = f"https://{domain}/items/destinations/{id}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {directus_token}"
    }

    try:
        response = await client_httpx.patch(api_url, json=fields, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error updating Directus API: {e}")

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

async def ayrshare_get_active_accounts(client_httpx: httpx.AsyncClient, profile_key: str):
    """Return the list of social platforms currently linked to the given profile.

    Used to check whether a network still exists before trying to unlink it. If the
    call fails (e.g. timeout) it raises, so the caller can stop and avoid clearing
    local state while the real Ayrshare state is unknown.
    """
    headers = {
        'Authorization': f"Bearer {AYRSHARE_API_KEY}",
        'Profile-Key': profile_key
    }
    try:
        response = await client_httpx.get("https://api.ayrshare.com/api/user", headers=headers)
        response.raise_for_status()
        # activeSocialAccounts is omitted entirely when nothing is linked.
        return response.json().get("activeSocialAccounts", [])
    except httpx.HTTPStatusError as e:
        # 403/404 means the profile no longer exists on Ayrshare (e.g. it was already
        # deleted, so its Profile-Key is now invalid). Treat it as "nothing linked" so
        # the caller cleans up local state instead of failing.
        if e.response.status_code in (403, 404):
            return []
        raise HTTPException(status_code=500, detail=f"Error fetching Ayrshare active accounts: {e}")
    except httpx.HTTPError as e:
        # Network/timeout error -> real state unknown -> propagate so we don't clear local data.
        raise HTTPException(status_code=500, detail=f"Error fetching Ayrshare active accounts: {e}")

async def ayrshare_delete_network(client_httpx: httpx.AsyncClient, profile_key: str, platform: str):
    headers = {
        'Authorization': f"Bearer {AYRSHARE_API_KEY}",
        'Content-Type': 'application/json',
        'Profile-Key': profile_key
    }
    payload = {'platform': platform}
    try:
        # Unlink a single social network from the profile (keeps the profile itself).
        # NOTE: /api/profiles/social unlinks the network; /api/profiles/profile deletes the whole profile.
        response = await client_httpx.request(
            "DELETE",
            "https://api.ayrshare.com/api/profiles/social",
            headers=headers,
            json=payload
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        # 403/404 means the profile is already gone on Ayrshare -> the network is
        # effectively unlinked, so treat it as success and let local cleanup proceed.
        if e.response.status_code in (403, 404):
            return
        raise HTTPException(status_code=500, detail=f"Error deleting Ayrshare network: {e}")
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
    private_key = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA8T9eeYVkoWY8HEPZX+hcIxVxFzMSrKgV8XlaSG6ov6l2pRiv\n"
        "8iYZ3hflwe10ASm+5NUsVsD3+stuYjIbnhCawXs+6VfLV8myn8y+0DiGGExoHkLQ\n"
        "MgyIgzdJjEuoDdUf10ED8tFT6i3vdOp+onuH7c+HTT6KdtZEYOEQbVB+nOQvGk2C\n"
        "cCCi/FxUUwcLyLwgJRo8Mu4ObTX8nIi2fRpgMOMJT5J3TVa+qUGakubutB7asZ0/\n"
        "MOjnsU1bSlH2SmkxY2fJzYfvDf4J3BxyMB8qG2mnKAtH0SQFgQ3wLQArff2dn465\n"
        "GLV9aWHeluFQDOrt9llVobcyFUKDMlp9ok1FVwIDAQABAoIBAC8mM+grLmou6XOa\n"
        "vRq19n/y2lnu5Ojypus9TOxYGEnxLFuC8iwwzyBtaj2XE3OAvarKkPJZn32YEbhG\n"
        "U8h2NVC4Lij7vCWpqWv635YhXe/UywqTA06szWdbwFeXl74wV5tBvSxRRgXAOYsP\n"
        "o3VNEFlllGt/3B7yrIWEpym+MCioPPK/ifcV6wcL4r6/1EBCux4KPlx94TvjOJ36\n"
        "Ld3Aax5WLnpaAI6TnTEZYEEwEz9pw/nmgFOjwwGLPBucWcYXOEIq2fZxrdsGB7UC\n"
        "i8AtRESDDzqGJBp6qm7IKqiWatDBuaNn3+aIsNvmwlMRJBgrxcy0FV/t80PJ3LM1\n"
        "rsvG5PUCgYEA/s8MtxEC1FsbuIzHeUi6eMoRdNKmghU3TrHuNRmr6ZioVUb72FPA\n"
        "7v8tp64jZVeM8qsj/wH1FRjemZIalZuLGktTGJgR8/0JTb0e4LvRARn41InBj0df\n"
        "GEZX1unG1wNSOs3+lh7haXWFQi407mB/MbbfrkerheYGCmCUGtFVAUsCgYEA8mAW\n"
        "6v+AlEyhW8EUjQMKMMTYyFxY5vVNII5rOE7t7mPWjbA3qnc6dNxDY+W04zjflkQp\n"
        "wktP1CDY5KjTzlyFuM8WTG4KWzA3r48ARWucWXAZxpWqkvDTTxNONXgB44VNNe0B\n"
        "KlpSkOryAJNqaYCIW19tI/Vvl6S0pwHgFrzUUKUCgYEAioeqlASNk0INKiJveELQ\n"
        "DkddgjPcDrDWJtSZewj/67nxGpvC4/N02vqkqZsE513X5T6iDUvVIKkqrDdAeMHd\n"
        "uGfnP2G9sPaKjlcZaHjzwjOKkpJqRyk4TAxCSTdDwTWvCQVhOeCEED+yOS7B3C9e\n"
        "N3sC1M9mMx/BfPbQzlusaU0CgYAeIy6WV+DQD9s8gnygsBETUVa3SyxOw4+sjajt\n"
        "XnsdWlKyWYgCbULahwzmHgjo/AhpMd6TZzPs54ywmgGENmL2QOG/7SrifdNexAQ/\n"
        "nYraYCMEW1XTYZiUy4y8/0gU111raCXt8z8y/9PJmIrxxWavHeV/RCR1EajY31XS\n"
        "3fX0dQKBgBqE2iMfMnImPvdE31x6tRq14NOrwW3pCj1haWqk19Z3sabCM2LWzuEj\n"
        "eoDmX6CVHHN2E5N/VZc++QbGyOUsJBhUF4Okhaae+E0rhEtH7+MJJlf1H+jlUTAo\n"
        "pvrFxVCUqXlm39Fn79h4FMEsitHodP8Ng2ZCN5UIdWUM7bV7/tp/\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    payload = {
        "domain": "id-oqsv9",
        "privateKey": private_key,
        "profileKey": profile_key,
        "logout": True
    }
    headers = {
        'Authorization': f'Bearer {AYRSHARE_API_KEY}',
        'Content-Type': 'application/json'
    }
    try:
        response = await client_httpx.post("https://api.ayrshare.com/api/profiles/generateJWT", json=payload, headers=headers)
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

        # Step 2: call ayrshare delete profile if key exists
        if ayrshare_key:
            try:
                await ayrshare_delete_profile(client_httpx, ayrshare_key)
            except Exception as e:
                print(f"Warning: Ayrshare delete profile failed: {e}")

        # Step 3: update used = false and reset fields in mongodb
        try:
            query = {}
            if ayrshare_profile:
                query["profile"] = ayrshare_profile
            elif ayrshare_key:
                query["profileKey"] = ayrshare_key

            if query:
                query["domain"] = domain
                run_blocking(
                    profiles_collection.find_one_and_update,
                    query,
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

        # Translate our internal network name to the platform name Ayrshare expects
        # (e.g. "short" -> "youtube"). MongoDB keeps using the original name below.
        ayrshare_platform = NETWORK_TO_AYRSHARE.get(platform, platform)

        # Step 2: Make sure the network is actually gone on Ayrshare before we touch
        # our own data. We check existence first so that if a previous call timed out
        # *after* Ayrshare had already unlinked it, this retry just cleans up locally
        # instead of calling delete again.
        #
        # If Ayrshare errors/times out here (existence check OR unlink), we raise and
        # stop WITHOUT clearing MongoDB/Directus, so the state stays consistent and a
        # later retry can finish the job.
        if ayrshare_key:
            active_accounts = await ayrshare_get_active_accounts(client_httpx, ayrshare_key)
            if ayrshare_platform in active_accounts:
                # Still linked -> unlink it (raises on failure -> no cleanup below).
                await ayrshare_delete_network(client_httpx, ayrshare_key, ayrshare_platform)
            # else: already unlinked on Ayrshare -> fall through and clean up locally.

        # Step 3: Update MongoDB networks to False
        try:
            query = {}
            if ayrshare_profile:
                query["profile"] = ayrshare_profile
            elif ayrshare_key:
                query["profileKey"] = ayrshare_key

            if query:
                query["domain"] = domain
                run_blocking(
                    profiles_collection.find_one_and_update,
                    query,
                    {"$set": {f"networks.{platform}": False}},
                    upsert=True
                )
        except PyMongoError as e:
            raise HTTPException(status_code=500, detail=f"MongoDB update failed: {e}")

        # Step 4: Clear the unlinked account info back in Directus (key, profile, app_id)
        await update_directus_data(client_httpx, domain, id, {
            "key": None,
            "profile": None,
            "app_id": None
        })

        return {"status": "success", "message": f"{platform} network unlinked"}

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


# ===========================================================================
#  NEW API — operates on the `destinations` collection (multi-source/dest
#  redesign). The LEGACY endpoints above (idols/channels) are kept unchanged
#  for backward compatibility with the old system.
#
#  A destination row IS a single platform, so `platform` is read straight from
#  the record instead of being passed in the URL. Buttons only need the item id:
#    Link   -> GET /destinations/profile/{domain}/{id}
#    Unlink -> GET /destinations/delete-network/{domain}/{id}
#    Delete -> GET /destinations/delete-profile/{domain}/{id}
# ===========================================================================
@app.get("/destinations/profile/{domain}/{id}")
async def link_destination_profile(
    domain: str = Path(..., description="The Directus domain (e.g. tcreator.cloud)"),
    id: str = Path(..., description="The destinations item ID"),
):
    async with httpx.AsyncClient(verify=certifi.where(), timeout=60.0) as client_httpx:
        # Step 1: Read the destination; the platform comes from the record itself.
        dest = await get_destination_data(client_httpx, domain, id)
        platform = dest.get("platform")
        if not platform:
            raise HTTPException(status_code=400, detail="Platform not found in destination record.")

        # The MongoDB profile pool still tracks slots under tiktok/short.
        pool_network = PLATFORM_TO_POOL_NETWORK.get(platform, platform)

        # Step 2: Grab an unused profile slot from the pool for this network.
        try:
            query = {f"networks.{pool_network}": False, "domain": domain}
            profile_doc = run_blocking(profiles_collection.find_one, query).result()
            if not profile_doc:
                raise HTTPException(status_code=404, detail=f"No profiles available for {platform}.")
            profile = profile_doc.get("profile")
            profileKey = profile_doc.get("profileKey")
        except PyMongoError as e:
            raise HTTPException(status_code=500, detail=f"MongoDB query failed: {e}")

        # Step 3: Create the Ayrshare profile if this pool slot has no key yet.
        if not profileKey:
            profile_data = await ayrshare_create_profile(client_httpx, profile)
            if profile_data.get("status") != "success":
                raise HTTPException(status_code=400, detail="Ayrshare profile creation failed.")

            profileKey = profile_data.get("profileKey")
            refId = profile_data.get("refId")

            try:
                run_blocking(
                    profiles_collection.find_one_and_update,
                    {"profile": profile, "domain": domain},
                    {"$set": {
                        f"networks.{pool_network}": True,
                        "profileKey": profileKey,
                        "refId": refId,
                        "used": True
                    }},
                )
            except PyMongoError as e:
                raise HTTPException(status_code=500, detail=f"MongoDB update failed: {e}")
        else:
            try:
                run_blocking(
                    profiles_collection.find_one_and_update,
                    {"profile": profile, "domain": domain},
                    {"$set": {
                        f"networks.{pool_network}": True,
                        "used": True
                    }},
                )
            except PyMongoError as e:
                raise HTTPException(status_code=500, detail=f"MongoDB update failed: {e}")

        # Step 4: Write the profile key/name back onto the destination row.
        await update_destination_data(client_httpx, domain, id, {
            "account_key": profileKey,
            "profile": profile
        })

        # Step 5: Generate the JWT URL and redirect to the Ayrshare linking page.
        jwt_data = await ayrshare_generate_jwt(client_httpx, profileKey)
        if jwt_data.get("status") != "success":
            raise HTTPException(status_code=400, detail="JWT generation failed.")

        return RedirectResponse(url=jwt_data.get("url"), status_code=301)


@app.get("/destinations/delete-network/{domain}/{id}")
async def delete_destination_network(
    domain: str = Path(..., description="The Directus domain (e.g. tcreator.cloud)"),
    id: str = Path(..., description="The destinations item ID"),
):
    async with httpx.AsyncClient(verify=certifi.where(), timeout=60.0) as client_httpx:
        # Step 1: Read the destination (platform, key and profile come from the record).
        dest = await get_destination_data(client_httpx, domain, id)
        ayrshare_key = dest.get("account_key")
        ayrshare_profile = dest.get("profile")
        platform = dest.get("platform")

        if not platform:
            raise HTTPException(status_code=400, detail="Platform not found in destination record.")

        # `destinations.platform` is already the Ayrshare-native name -> no translation.
        ayrshare_platform = platform
        pool_network = PLATFORM_TO_POOL_NETWORK.get(platform, platform)

        # Step 2: Only unlink on Ayrshare if the network is actually still linked.
        # If Ayrshare errors/times out, we raise and stop WITHOUT clearing local state.
        if ayrshare_key:
            active_accounts = await ayrshare_get_active_accounts(client_httpx, ayrshare_key)
            if ayrshare_platform in active_accounts:
                await ayrshare_delete_network(client_httpx, ayrshare_key, ayrshare_platform)
            # else: already unlinked on Ayrshare -> fall through and clean up locally.

        # Step 3: Mark this network as free in the MongoDB pool.
        # NOTE: we only UNLINK the network from the Ayrshare profile (Step 2) — the
        # Ayrshare account/profile itself is kept, not deleted.
        try:
            query = {}
            if ayrshare_profile:
                query["profile"] = ayrshare_profile
            elif ayrshare_key:
                query["profileKey"] = ayrshare_key

            if query:
                query["domain"] = domain
                run_blocking(
                    profiles_collection.find_one_and_update,
                    query,
                    {"$set": {f"networks.{pool_network}": False}},
                    upsert=True
                )
        except PyMongoError as e:
            raise HTTPException(status_code=500, detail=f"MongoDB update failed: {e}")

        # Step 4: Clear the linked profile info back on the destination row
        # (key/profile/app_id) so the row shows as unlinked.
        await update_destination_data(client_httpx, domain, id, {
            "account_key": None,
            "profile": None,
            "app_id": None
        })

        return {"status": "success", "message": f"{platform} network unlinked"}


@app.get("/destinations/delete-profile/{domain}/{id}")
async def delete_destination_profile(
    domain: str = Path(..., description="The Directus domain (e.g. tcreator.cloud)"),
    id: str = Path(..., description="The destinations item ID"),
):
    async with httpx.AsyncClient(verify=certifi.where(), timeout=60.0) as client_httpx:
        # Step 1: Read the destination.
        dest = await get_destination_data(client_httpx, domain, id)
        ayrshare_key = dest.get("account_key")
        ayrshare_profile = dest.get("profile")

        # Step 2: Delete the whole Ayrshare profile if a key exists.
        if ayrshare_key:
            try:
                await ayrshare_delete_profile(client_httpx, ayrshare_key)
            except Exception as e:
                print(f"Warning: Ayrshare delete profile failed: {e}")

        # Step 3: Reset the pool doc so its slot becomes available again.
        try:
            query = {}
            if ayrshare_profile:
                query["profile"] = ayrshare_profile
            elif ayrshare_key:
                query["profileKey"] = ayrshare_key

            if query:
                query["domain"] = domain
                run_blocking(
                    profiles_collection.find_one_and_update,
                    query,
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

        # Step 4: Clear the linked account info back on the destination row.
        await update_destination_data(client_httpx, domain, id, {
            "account_key": None,
            "app_id": None
        })

        return {"status": "success", "message": "Profile deleted successfully"}
