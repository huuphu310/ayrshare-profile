#!/usr/bin/env python3
import os
import sys
from crontab import CronTab

def add_cronjob(script_name, job_comment, interval_hours=1):
    """Add a cronjob to run the specified script at regular intervals.
    
    Args:
        script_name: Name of the script file to run
        job_comment: Comment to identify the cronjob
        interval_hours: How often to run the job (in hours)
    
    Returns:
        The created cron job object
    """
    script_path = os.path.join(script_dir, script_name)
    
    # Remove any existing jobs with this comment
    for job in cron.find_comment(job_comment):
        cron.remove(job)
    
    # Create a new job
    job = cron.new(command=f"cd {script_dir} && python3 {script_path}", comment=job_comment)
    job.hour.every(interval_hours)
    
    return job

# Get the current directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

try:
    # Create a cron object for the current user
    cron = CronTab(user=True)
    
    # Add cronjobs for different scripts
    add_cronjob("check_ayrshare_errors.py", "ayrshare_error_check")
    add_cronjob("check_profiles.py", "ayrshare_profile_check")
    
    # Write the changes to the crontab
    cron.write()
    
    print("Cronjobs installed successfully. The scripts will run every hour.")
    
except Exception as e:
    print(f"Error setting up cronjobs: {e}", file=sys.stderr)
    sys.exit(1)
