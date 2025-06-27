from pymongo import MongoClient
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "your_database_name")


def update_profiles():
    # Initialize MongoDB client
    client = MongoClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    profiles_collection = db["profiles"]

    try:
        # Update all documents that don't have networks field
        result = profiles_collection.update_many(
            {"networks": {"$exists": False}},
            {
                "$set": {
                    "networks": {
                        "tiktok": True,
                        "short": False
                    }
                }
            }
        )

        print(f"Modified {result.modified_count} documents")

        # Double check all documents now have networks field
        total_docs = profiles_collection.count_documents({})
        docs_with_networks = profiles_collection.count_documents({"networks": {"$exists": True}})

        print(f"\nTotal documents: {total_docs}")
        print(f"Documents with networks field: {docs_with_networks}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    print("Starting database update...")
    update_profiles()
    print("Database update completed!")
