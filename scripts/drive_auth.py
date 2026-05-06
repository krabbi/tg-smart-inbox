"""One-time Google Drive OAuth 2.0 authorization.

Generates token.json which the bot loads on every subsequent run.
Works on remote/headless servers — no browser on the server required.

Usage on the server (Docker):

    docker compose run --rm -it bot python scripts/drive_auth.py

Steps:
    1. The script prints an authorization URL.
    2. Open that URL in any browser (on your laptop, phone, etc.).
    3. Grant access — Google will try to redirect to http://localhost:8080/?code=...
       That page will NOT load (expected — there is no server there).
    4. Copy the full URL from the browser address bar and paste it into the terminal.
    5. token.json is written automatically.

Optional arguments:
    --credentials PATH   path to OAuth client secrets JSON  (default: $GOOGLE_DRIVE_CREDENTIALS_FILE or credentials.json)
    --token PATH         path to write the token            (default: $GOOGLE_DRIVE_TOKEN_FILE or token.json)
    --port PORT          port used in the redirect URI      (default: 8080)
"""

import argparse
import os
import sys

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

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
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port used in the redirect URI (default: 8080)",
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
    flow.redirect_uri = f"http://localhost:{args.port}/"

    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

    print("\n" + "=" * 60)
    print("Open this URL in your browser (laptop, phone — any device):")
    print()
    print(f"  {auth_url}")
    print()
    print("After granting access, the browser will try to open:")
    print(f"  http://localhost:{args.port}/")
    print("That page will NOT load — this is expected.")
    print()
    print("Copy the FULL URL from the browser address bar and paste below.")
    print("=" * 60 + "\n")

    redirect_response = input("Paste the full redirect URL: ").strip()

    try:
        flow.fetch_token(authorization_response=redirect_response)
    except Exception as exc:
        print(f"\nERROR: failed to exchange authorization code: {exc}", file=sys.stderr)
        sys.exit(1)

    creds = flow.credentials
    with open(args.token, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())

    print(f"\n✅ Authorization successful. Token saved to: {args.token}")
    print("You can now start the bot normally.")


if __name__ == "__main__":
    main()
