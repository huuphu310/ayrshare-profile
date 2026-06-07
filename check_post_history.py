import os
import httpx
import asyncio
import pymongo
import datetime
import logging
from dotenv import load_dotenv
from telegram import Bot

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler("ayrshare_error_check.log")]
)
logger = logging.getLogger(__name__)

# MongoDB connection
mongo_client = pymongo.MongoClient("mongodb://localhost:27017/")
db = mongo_client[os.getenv("DATABASE_NAME", "ayrshare")]
profiles_collection = db["profiles"]
post_errors_collection = db["post_errors"]

# Ayrshare API details
AYRSHARE_API_KEY = os.getenv("AYRSHARE_API_KEY")

# Telegram bot configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


async def check_profile_errors(profile_key, profile_name):
    """Check for error posts for a specific profile"""
    try:
        # Get start and end date for the last 24 hours
        end_date = datetime.datetime.utcnow()
        start_date = end_date - datetime.timedelta(hours=72)

        # Format dates for Ayrshare API
        start_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Prepare URL and headers
        url = f"https://api.ayrshare.com/api/history?startDate={start_date_str}&endDate={end_date_str}&status=error"
        headers = {
            'Authorization': f'Bearer {AYRSHARE_API_KEY}',
            'Profile-Key': profile_key
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)

            # Handle the case when no history is found (returns 400)
            if response.status_code == 400 and "History not found" in response.text:
                logger.info(f"No error history found for profile {profile_name}")
                return 0, []

            # For other errors, raise an exception
            response.raise_for_status()

            data = response.json()
            error_posts = data.get("history", [])
            new_error_count = 0

            for post in error_posts:
                post_id = post.get("id")
                if post_id:
                    # Check if this error post is already in the database

                    existing_error = post_errors_collection.find_one({"id": post_id})
                    if not existing_error:
                        # Add profile info to the post data
                        post["profile_name"] = profile_name
                        post["profile_key"] = profile_key
                        post["detected_at"] = datetime.datetime.utcnow()

                        # Insert into error collection
                        post_errors_collection.insert_one(post)
                        new_error_count += 1

            return new_error_count, error_posts

    except Exception as e:
        logger.error(f"Error checking profile {profile_name}: {str(e)}")
        return 0, []


async def send_telegram_alert(error_summary):
    """Send alert to Telegram if configured"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram bot not configured. Skipping alert.")
        return

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        message = "🚨 AYRSHARE POST ERROR ALERT 🚨\n\n"
        message += "The following profiles have new post errors:\n\n"

        for profile, count in error_summary.items():
            message += f"Profile: {profile} - {count} new errors\n"

        message += "\nPlease check the post_errors collection for details."

        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logger.info("Telegram alert sent successfully")

    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {str(e)}")


async def main():
    """Main function to check all profiles for errors"""
    try:
        # Find all profiles that are in use
        active_profiles = profiles_collection.find({"used": True})

        error_summary = {}
        total_new_errors = 0

        # Check each profile for errors
        for profile_doc in active_profiles:
            profile_name = profile_doc.get("profile")
            profile_key = profile_doc.get("profileKey")

            if not profile_key:
                logger.warning(f"Profile {profile_name} has no profileKey. Skipping.")
                continue

            logger.info(f"Checking errors for profile {profile_name}")
            new_error_count, _ = await check_profile_errors(profile_key, profile_name)

            if new_error_count > 0:
                error_summary[profile_name] = new_error_count
                total_new_errors += new_error_count
                logger.info(f"Found {new_error_count} new errors for profile {profile_name}")

        # Send alert if there are more than 10 new errors
        if total_new_errors >= 10:
            logger.warning(f"Found {total_new_errors} new errors across all profiles. Sending alert.")
            await send_telegram_alert(error_summary)
        else:
            logger.info(f"Found {total_new_errors} new errors across all profiles. Below threshold for alert.")

    except Exception as e:
        logger.error(f"Error in main function: {str(e)}")


if __name__ == "__main__":
    asyncio.run(main())