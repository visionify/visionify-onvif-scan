"""Interactive credential handling with in-memory reuse across cameras."""
from __future__ import annotations

import getpass
from typing import List, Optional, Tuple

from .config import DEFAULT_CREDENTIALS


class CredentialStore:
    """Holds creds in memory only. Tries known/working creds before prompting."""

    def __init__(self, cli_user: str = "", cli_pass: str = "", no_prompt: bool = False):
        self.no_prompt = no_prompt
        # ordered list of (user, pass) to try; CLI-provided first, then a working
        # credential remembered from a previous camera, then vendor defaults.
        self.known: List[Tuple[str, str]] = []
        if cli_user:
            self.known.append((cli_user, cli_pass))
        self.last_working: Optional[Tuple[str, str]] = None

    def candidates(self) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        if self.last_working:
            out.append(self.last_working)
        out.extend(c for c in self.known if c not in out)
        out.extend(c for c in DEFAULT_CREDENTIALS if c not in out)
        return out

    def remember(self, user: str, password: str) -> None:
        self.last_working = (user, password)
        if (user, password) not in self.known:
            self.known.append((user, password))

    def prompt(self, ip: str) -> Optional[Tuple[str, str]]:
        if self.no_prompt:
            return None
        # offer to reuse the last working credential as the default
        default_user = self.last_working[0] if self.last_working else "admin"
        try:
            print(f"\n  Camera {ip} needs credentials.")
            user = input(f"    username [{default_user}]: ").strip() or default_user
            password = getpass.getpass("    password: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        return (user, password)
