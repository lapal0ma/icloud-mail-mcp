from dotenv import load_dotenv
import os

load_dotenv()

ICLOUD_EMAIL = os.getenv("ICLOUD_EMAIL")
ICLOUD_APP_PASSWORD = os.getenv("ICLOUD_APP_PASSWORD")

if not ICLOUD_EMAIL or not ICLOUD_APP_PASSWORD:
    raise SystemExit(
        "\n"
        "Missing iCloud credentials. Follow these steps:\n"
        "\n"
        "  1. Copy the example env file:\n"
        "       cp .env.example .env\n"
        "\n"
        "  2. Open .env and fill in your credentials:\n"
        "       ICLOUD_EMAIL=your_apple_id@icloud.com\n"
        "       ICLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx\n"
        "\n"
        "  3. Generate an App-Specific Password at:\n"
        "       https://appleid.apple.com\n"
        "       -> Sign In -> App-Specific Passwords -> Generate\n"
        "\n"
        "  WARNING: Never use your real iCloud password here.\n"
        "  WARNING: Never commit your .env file to version control.\n"
    )
