from fastapi import FastAPI, HTTPException, Request
import httpx
from starlette.responses import JSONResponse
import asyncio
import json
import redis.asyncio as redis
import hmac
import hashlib
import base64
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

BOKUN_ACCESS_KEY = os.environ.get('BOKUN_ACCESS_KEY')
BOKUN_SECRET_KEY = os.environ.get('BOKUN_SECRET_KEY')
BOKUN_BASE_URL = os.environ.get('BOKUN_BASE_URL')
CACHE_EXPIRATION = os.environ.get('CACHE_EXPIRATION')
REDIS_URL = os.environ.get('REDIS_URL')

app = FastAPI()

TARGET_API_URL = BOKUN_BASE_URL + "/activity.json/search"

# Kết nối tới Redis (sử dụng None nếu không kết nối được)
redis_client = None

try:
    redis_client = redis.from_url(REDIS_URL)
except Exception as e:
    print(f"Could not connect to Redis: {e}")


# Hàm tạo key cho Redis từ request
async def create_cache_key(request: Request) -> str:
    unique_string = f"{request.method}-{request.url.path}-{await request.body()}"
    return hashlib.sha256(unique_string.encode('utf-8')).hexdigest()


# Hàm lưu dữ liệu vào Redis
async def set_cache_data(key: str, data: dict):
    if redis_client:
        try:
            await redis_client.setex(key, CACHE_EXPIRATION, json.dumps(data))
        except Exception as e:
            print(f"Failed to save cache to Redis: {e}")


# Hàm lấy dữ liệu từ Redis
async def get_cache_data(key: str) -> dict:
    if redis_client:
        try:
            cached_data = await redis_client.get(key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            print(f"Failed to retrieve cache from Redis: {e}")
    return None


async def forward_request(request: Request):
    resonse_headers = {
        "Content-Type": "application/json ; charset=utf-8",
        "Access-Control-Allow-Origin": "*"
    }
    cache_key = await create_cache_key(request)

    # Kiểm tra cache trước
    cached_response = await get_cache_data(cache_key)
    if cached_response:
        return JSONResponse(content=cached_response, headers=resonse_headers)

    d = datetime.utcnow()
    bokun_date = d.strftime('%Y-%m-%d %H:%M:%S')

    http_method = "POST"
    relative_path = TARGET_API_URL.replace(BOKUN_BASE_URL, "")
    # Xây dựng chuỗi để ký
    str_to_sign = f"{bokun_date}{BOKUN_ACCESS_KEY}{http_method}{relative_path}"

    # Tạo chữ ký HMAC-SHA1 và mã hóa Base64
    hash = hmac.new(BOKUN_SECRET_KEY.encode(), str_to_sign.encode(), hashlib.sha1)
    signature = base64.b64encode(hash.digest()).decode()

    async with httpx.AsyncClient() as client:
        try:
            headers = {
                'X-Bokun-AccessKey': BOKUN_ACCESS_KEY,
                'X-Bokun-Date': bokun_date,
                'X-Bokun-Signature': signature,
                'Content-Type': 'application/json ; charset=utf-8'
            }
            payload = json.dumps({
                "page": 1,
                "pageSize": 50
            })
            response = await client.request(
                method="POST",
                url=TARGET_API_URL,
                headers=headers,
                timeout=5.0,
                data=payload  # Timeout sau 5 giây
            )

            response.encoding = 'utf-8'
            response_data = response.json()

            # Lưu vào cache
            await set_cache_data(cache_key, response_data)

            return JSONResponse(content=response_data, status_code=response.status_code, headers=resonse_headers)

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Upstream service timeout")

        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="Upstream service returned an error")

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.route("/", methods=["GET"])
async def proxy(request: Request):
    return await forward_request(request)