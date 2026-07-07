import os
# from sshtunnel import SSHTunnelForwarder
from pymongo import MongoClient, ASCENDING
from pymongo.errors import PyMongoError, DuplicateKeyError
from dotenv import load_dotenv

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

# Set up SSH tunnel
# server = SSHTunnelForwarder(
#     (SSH_HOST, SSH_PORT),
#     ssh_username=SSH_USER,
#     ssh_pkey=SSH_KEY_PATH,
#     remote_bind_address=(MONGODB_HOST, MONGODB_PORT)
# )

# Start the SSH tunnel
#server.start()

def populate_profiles(first_char, domain, f, t):
    client = MongoClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    profiles_collection = db[PROFILES_COLLECTION]

    # Create a unique index on the 'title' field to prevent duplicates
    # try:
    #     profiles_collection.create_index([("title", ASCENDING)], unique=True)
    #     print("Unique index on 'title' created successfully.")
    # except PyMongoError as e:
    #     print(f"An error occurred while creating index: {e}")
    #     client.close()
    #     return

    # Generate titles from D41 to D80
    profiles = [{"profile": f"{first_char}{num:02}", "used": False, "domain": domain,"networks": {
    "tiktok": False,
    "short": False
  }} for num in range(f, t + 1)]

    try:
        # Insert many documents
        result = profiles_collection.insert_many(profiles, ordered=False)
        print(f"Inserted {len(result.inserted_ids)} documents into the '{PROFILES_COLLECTION}' collection.")
    except DuplicateKeyError as e:
        print("Some titles already exist in the collection. Skipping duplicates.")
        print(f"Details: {e.details}")
    except PyMongoError as e:
        print(f"An error occurred while inserting documents: {e}")
    finally:
        client.close()

def add_domain_to_profiles():
    client = MongoClient(f"mongodb://localhost:{server.local_bind_port}")
    db = client[DATABASE_NAME]
    profiles_collection = db[PROFILES_COLLECTION]

    try:
        result = profiles_collection.update_many(
            {},  # Update all documents
            {"$set": {"domain": "dcreator.cloud"}}
        )
        print(f"Updated {result.modified_count} documents in the '{PROFILES_COLLECTION}' collection.")
    except PyMongoError as e:
        print(f"An error occurred while updating documents: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    # add_domain_to_profiles()
    populate_profiles("C", "ccreator.site", 51, 60)
    #server.stop()