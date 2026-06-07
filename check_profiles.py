#!/usr/bin/env python3
import os
import requests
import json
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("profile_check.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def connect_to_mongodb():
    """Connect to MongoDB database."""
    try:
        client = MongoClient('localhost', 27017)
        db = client[os.getenv('DATABASE_NAME')]
        return db
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        return None


def get_ayrshare_profiles():
    """Fetch profiles from Ayrshare API."""
    try:
        url = "https://api.ayrshare.com/api/profiles"
        headers = {
            "Authorization": f"Bearer {os.getenv('AYRSHARE_API_KEY')}"
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        return response.json()['profiles']
    except Exception as e:
        logger.error(f"Failed to fetch profiles from Ayrshare API: {e}")
        return []


def send_telegram_notification(message):
    """Send notification to Telegram."""
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        response = requests.post(url, data=data)
        response.raise_for_status()
        logger.info(f"Telegram notification sent successfully")
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")


def check_profiles():
    """Check profiles status and send alerts if necessary."""
    logger.info("Starting profile check...")

    # Get profiles from API
    profiles = get_ayrshare_profiles()

    if not profiles:
        send_telegram_notification("⚠️ <b>ALERT</b>: Failed to retrieve profiles from Ayrshare API")
        return

    # Check each profile for issues
    problem_profiles = []

    for profile in profiles:
        issues = []

        # Check if profile has active social accounts
        if not profile.get('activeSocialAccounts') or len(profile.get('activeSocialAccounts', [])) == 0:
            issues.append("No active social accounts")

        # Check if profile status is not 'active'
        if profile.get('status') != 'active':
            issues.append(f"Status is '{profile.get('status')}' (not active)")

        if issues:
            problem_profiles.append({
                "title": profile.get('title', 'Unknown'),
                "issues": issues,
                "profile_data": profile
            })

    # Send notifications for problem profiles
    if problem_profiles:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = f"⚠️ <b>AYRSHARE PROFILE ISSUES DETECTED</b> ⚠️\n<i>Time: {now}</i>\n\n"

        for profile in problem_profiles:
            message += f"<b>Profile: {profile['title']}</b>\n"
            message += "Issues:\n"
            for issue in profile['issues']:
                message += f"- {issue}\n"
            message += "\n"

        send_telegram_notification(message)
        logger.warning(f"Found {len(problem_profiles)} profiles with issues")
    else:
        logger.info("All profiles are healthy")


if __name__ == "__main__":
    check_profiles()