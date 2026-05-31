"""
Run this ONCE locally to authenticate yt-dlp with Google OAuth2.
This gives yt-dlp full access to YouTube from any IP.

Steps:
  1. python auth_ytdlp.py
  2. Open the URL shown → enter the code → sign in with Google
  3. Press Enter here
  4. Copy the YT_OAUTH2_TOKEN value shown → set on Render
"""
import subprocess, sys, os, base64, glob, json, pathlib, time


def find_token_file():
    """Find where yt-dlp-youtube-oauth2 stored the token."""
    home = pathlib.Path.home()
    patterns = [
        home / ".cache" / "yt-dlp-youtube-oauth2" / "*.json",
        home / ".config" / "yt-dlp-youtube-oauth2" / "*.json",
        home / ".yt-dlp-youtube-oauth2" / "*.json",
    ]
    for pattern in patterns:
        matches = list(pathlib.Path(pattern.parent).glob(pattern.name)) if pattern.parent.exists() else []
        if matches:
            return matches[0]
    return None


def main():
    ytdlp = sys.executable.replace("python", "yt-dlp").replace(
        "python3", "yt-dlp"
    )
    # Use the .venv yt-dlp on Windows
    venv_ytdlp = os.path.join(os.path.dirname(sys.executable), "yt-dlp.exe")
    if os.path.exists(venv_ytdlp):
        ytdlp = venv_ytdlp

    print("=" * 60)
    print("yt-dlp YouTube OAuth2 Token Generator")
    print("=" * 60)

    # Delete any old/revoked token first
    old = find_token_file()
    if old:
        old.unlink()
        print(f"Removed old token: {old}")

    print("\nStarting OAuth2 flow...")
    print("You will see a URL and a code below.")
    print("1. Open the URL in Chrome")
    print("2. Enter the code")
    print("3. Sign in with your Google account")
    print("4. Come back here and press ENTER\n")

    # Run yt-dlp with oauth2 — it will print URL + code and poll
    proc = subprocess.Popen(
        [ytdlp, "--username", "oauth2", "--password", "",
         "--skip-download", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    # Print output until we see the device URL
    for line in proc.stdout:
        print(line, end="")
        if "google.com/device" in line:
            break

    input("\n>>> Press ENTER after you have completed the Google sign-in...\n")

    # Give yt-dlp time to complete the token exchange
    time.sleep(3)
    proc.terminate()

    # Find the saved token
    for _ in range(10):
        token_file = find_token_file()
        if token_file and token_file.exists():
            break
        time.sleep(1)
    else:
        print("ERROR: Token file not found. Try running yt-dlp manually:")
        print(f'  {ytdlp} --username oauth2 --password "" https://youtu.be/dQw4w9WgXcQ')
        sys.exit(1)

    b64 = base64.b64encode(token_file.read_bytes()).decode("ascii")
    print("\n" + "=" * 60)
    print("SUCCESS! Set this on Render:")
    print("  Key:   YT_OAUTH2_TOKEN")
    print("  Value: (copy the string below)")
    print("=" * 60)
    print(b64)
    print("=" * 60)
    print(f"\nToken saved at: {token_file}")


if __name__ == "__main__":
    main()
