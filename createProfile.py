import os
from sshtunnel import SSHTunnelForwarder
from pymongo import MongoClient, ASCENDING, errors
from pymongo.errors import PyMongoError, DuplicateKeyError
from dotenv import load_dotenv
import requests
# Load environment variables from .env file
load_dotenv()

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "your_database_name")
PROFILES_COLLECTION = "profiles"
SSH_HOST = os.getenv("SSH_HOST", "your_ssh_host")
SSH_PORT = int(os.getenv("SSH_PORT", 22))
SSH_USER = os.getenv("SSH_USER", "your_ssh_user")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", "/path/to/your/ssh/key")
MONGODB_HOST = os.getenv("MONGODB_HOST", "localhost")
MONGODB_PORT = int(os.getenv("MONGODB_PORT", 27017))
DIRECTUS_URL = os.environ.get('DIRECTUS_URL')
DIRECTUS_AUTH_TOKEN = os.environ.get('DIRECTUS_AUTH_TOKEN')

# Set up SSH tunnel
server = SSHTunnelForwarder(
    (SSH_HOST, SSH_PORT),
    ssh_username=SSH_USER,
    ssh_pkey=SSH_KEY_PATH,
    remote_bind_address=(MONGODB_HOST, MONGODB_PORT)
)

# Start the SSH tunnel
server.start()

client = MongoClient(f"mongodb://localhost:{server.local_bind_port}")
db = client[DATABASE_NAME]
collection = db[PROFILES_COLLECTION]

def insert_document(domain, profile, profileKey):
    # Kết nối đến MongoDB

    # Tạo dữ liệu bản ghi mới
    new_document = {
        "used": True,
        "domain": domain,
        "profile": profile,
        "profileKey": profileKey
    }
    try:
        # Chèn bản ghi mới vào MongoDB
        result = collection.insert_one(new_document)
        print("Thêm mới thành công với ID:", result.inserted_id)
    except errors.DuplicateKeyError:
        print(f"Lỗi: Profile '{profile}' đã tồn tại trong cơ sở dữ liệu.")

    # Đóng kết nối

def get_idol():
    try:
        url = DIRECTUS_URL + "/items/idols?filter[status]=active&filter[noti_only]=0"

        payload = {}
        headers = {
            'Authorization': DIRECTUS_AUTH_TOKEN
        }

        response = requests.request("GET", url, headers=headers, data=payload)
        if response.status_code == 200:
            return response.json()['data']
        else:
            return []
    except Exception as e:
        print(f"Error in get idol: {str(e)}")
        return []

if __name__ == "__main__":
    idols = get_idol()
    for idol in idols:
        key = idol['key']
        profile = idol['profile']
        if key and profile:
            insert_document("tcreator.cloud", profile, key)
    client.close()
    server.stop()