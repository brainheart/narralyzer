#!/usr/bin/env python3
"""Collect an API key in a native hidden-input dialog; never print its value."""

import getpass
import re
import subprocess
import sys

from keyring.backends.macOS import Keyring
from keyring.errors import KeyringError


def main():
    if sys.platform != "darwin":
        sys.exit("This setup dialog requires macOS.")
    result = subprocess.run(
        ["osascript", "-e", '''
        with timeout of 3600 seconds
        tell application "System Events"
            activate
            set answer to display dialog "Paste your OpenAI API key. I will save it in macOS Keychain for Narralyzer. The key will not appear in chat or be saved in the project." default answer "" with hidden answer with title "Narralyzer — API key" buttons {"Cancel", "Save"} default button "Save" cancel button "Cancel"
            return text returned of answer
        end tell
        end timeout
        '''],
        capture_output=True, text=True,
    )
    if result.returncode:
        # Report only an OS error number, never captured dialog contents.
        codes = re.findall(r"\((-?\d+)\)", result.stderr)
        code = codes[-1] if codes else "unknown"
        sys.exit(f"Setup cancelled or dialog unavailable (OS error {code}); no key saved.")
    key = result.stdout.strip()
    if not key or any(char.isspace() for char in key):
        sys.exit("The key was empty or contained whitespace; no key saved.")
    try:
        Keyring().set_password("narralyzer-openai-api", getpass.getuser(), key)
    except KeyringError:
        sys.exit("Keychain did not accept the key. Its value was not displayed.")
    print("API key saved in macOS Keychain. Its value was not displayed.")


if __name__ == "__main__":
    main()
