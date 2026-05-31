"""
Run this script ONCE locally to generate a YouTube OAuth token.
The token lets the server download videos without bot detection.

Steps:
  1.  python auth_setup.py
  2.  Open the Google URL shown
  3.  Enter the code shown
  4.  Copy the YT_OAUTH_TOKEN value and set it on Render
"""

import base64
import os
import pathlib
import sys


def main():
    try:
        from pytubefix import YouTube
        from pytubefix.innertube import _token_file
    except ImportError:
        print("ERROR: pytubefix not installed. Run:  pip install pytubefix")
        sys.exit(1)

    token_path = pathlib.Path(_token_file)
    print("=" * 60)
    print("YouTube OAuth Token Generator")
    print("=" * 60)
    print()

    # If token already exists, just show it
    if token_path.exists():
        print("Token already exists at:", token_path)
        _print_token(token_path)
        return

    print("Starting OAuth device flow...")
    print("You will see a URL and a short code.")
    print("1. Open the URL in your browser")
    print("2. Enter the code")
    print("3. Log in with your Google account")
    print("4. Come back here and press ENTER")
    print()

    try:
        # This triggers the OAuth flow interactively
        yt = YouTube(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            use_oauth=True,
            allow_oauth_cache=True,
        )
        _ = yt.title  # Forces the token fetch
    except Exception as exc:
        print(f"\nError during OAuth: {exc}")
        sys.exit(1)

    if token_path.exists():
        print("\nOAuth completed successfully!")
        _print_token(token_path)
    else:
        print("\nERROR: Token file not found at:", token_path)
        sys.exit(1)


def _print_token(token_path: pathlib.Path):
    token_b64 = base64.b64encode(token_path.read_bytes()).decode("ascii")
    print()
    print("=" * 60)
    print("Copy this value and set it on Render as:")
    print("  Key:   YT_OAUTH_TOKEN")
    print("  Value: (the long string below)")
    print("=" * 60)
    print(token_b64)
    print("=" * 60)


if __name__ == "__main__":
    main()
