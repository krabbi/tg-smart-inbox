"""One-time Google Drive OAuth 2.0 authorization.

Generates token.json which the bot loads on every subsequent run.
Must be executed interactively — it will print a URL and prompt for the auth code.

Usage on the server (Docker):

    docker compose run --rm -it bot python scripts/drive_auth.py

Usage for local development:

    python scripts/drive_auth.py

Optional arguments:
    --credentials PATH   path to OAuth client secrets JSON  (default: $GOOGLE_DRIVE_CREDENTIALS_FILE or credentials.json)
    --token PATH         path to write the token            (default: $GOOGLE_DRIVE_TOKEN_FILE or token.json)
"""

import argparse
import os
import sys

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize Google Drive OAuth 2.0")
    parser.add_argument(
        "--credentials",
        default=os.getenv("GOOGLE_DRIVE_CREDENTIALS_FILE", "credentials.json"),
        help="OAuth 2.0 client secrets JSON (Desktop app)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GOOGLE_DRIVE_TOKEN_FILE", "token.json"),
        help="Output path for the user token",
    )
    args = parser.parse_args()

    if not os.path.exists(args.credentials):
        print(f"ERROR: credentials file not found: {args.credentials}", file=sys.stderr)
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib is not installed", file=sys.stderr)
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(args.credentials, _SCOPES)
    creds = flow.run_console()

    with open(args.token, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())

    print(f"\n✅ Authorization successful. Token saved to: {args.token}")
    print("You can now start the bot normally.")


if __name__ == "__main__":
    main()
