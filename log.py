"""Small timestamped logger shared by every module."""

from datetime import datetime


def log(msg):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}')
