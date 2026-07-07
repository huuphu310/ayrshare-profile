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

def get_profile_keys():
    result = collection.find({"domain": "tcreator.cloud"}, {"profileKey": 1, "_id": 0})

    # Lấy toàn bộ giá trị profileKey từ các kết quả tìm kiếm
    profile_keys = [doc["profileKey"] for doc in result]
    return profile_keys

def get_posts():
    try:
        url = DIRECTUS_URL + '/items/videos?filter[status]=success&sort=-date_created&limit=500'

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
        print(f"Error in get_posts {str(e)}")
        return []


if __name__ == "__main__":
    profile_keys = get_profile_keys()
    client.close()
    server.stop()
    posts = get_posts()
    for post in posts:
        key = post['key']
        if key not in profile_keys:
            print(f"Key {key} not in profile keys")
