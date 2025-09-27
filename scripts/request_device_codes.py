#!/usr/bin/env python3
"""Initiate the BMW CarData device authorization flow and display the resulting codes."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import secrets
import sys
from typing import Dict, List

import requests

DEVICE_CODE_URL_DEFAULT = "https://customer.bmwgroup.com/gcdm/oauth/device/code"
TOKEN_URL_DEFAULT = "https://customer.bmwgroup.com/gcdm/oauth/token"


def _generate_code_verifier(length: int = 86) -> str:
    """Return a PKCE code verifier (43-128 characters)."""
    if length < 43 or length > 128:
        raise ValueError("length must be between 43 and 128 characters")
    while True:
        verifier = secrets.token_urlsafe(length)
        if 43 <= len(verifier) <= 128:
            return verifier


def _generate_code_challenge(code_verifier: str) -> str:
    """Create the S256 PKCE code challenge for the verifier."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def request_device_code(
    client_id: str,
    scopes: List[str],
    device_code_url: str,
) -> Dict:
    """Call the device code endpoint and return the JSON payload."""
    code_verifier = _generate_code_verifier()
    code_challenge = _generate_code_challenge(code_verifier)

    payload = {
        "client_id": client_id,
        "response_type": "device_code",
        "scope": " ".join(scopes),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    response = requests.post(
        device_code_url,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=payload,
        timeout=30,
    )
    response.raise_for_status()

    response_json = response.json()
    response_json["code_verifier"] = code_verifier
    response_json["code_challenge"] = code_challenge
    response_json["scope"] = payload["scope"]
    response_json["client_id"] = client_id
    response_json["device_code_url"] = device_code_url
    response_json["token_url"] = TOKEN_URL_DEFAULT
    response_json["requested_at"] = dt.datetime.utcnow().isoformat() + "Z"
    return response_json


def _print_summary(data: Dict) -> None:
    """Pretty-print next steps to stdout."""
    friendly = {
        "Client ID": data["client_id"],
        "Device code": data["device_code"],
        "User code": data["user_code"],
        "Verification URL": data.get("verification_uri_complete") or data.get("verification_uri"),
        "Expires in (seconds)": data.get("expires_in"),
        "Poll interval (seconds)": data.get("interval"),
        "Code verifier": data["code_verifier"],
        "Token URL": data.get("token_url"),
        "Scopes": data["scope"],
    }

    max_key_len = max(len(key) for key in friendly)
    print("\nDevice authorization initiated. Provide the details below during the next step:\n")
    for key, value in friendly.items():
        print(f"{key:<{max_key_len}} : {value}")
    print(
        "\nKeep the code verifier somewhere safe. You will need it when exchanging the device code for tokens."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start the BMW CarData Device Code flow and capture the generated codes.",
    )
    parser.add_argument("--client-id", required=True, help="Client ID generated in the BMW portal")
    parser.add_argument(
        "--scopes",
        nargs="+",
        default=["authenticate_user", "openid", "cardata:api:read"],
        help="Space-separated list of scopes to request",
    )
    parser.add_argument(
        "--device-code-url",
        default=DEVICE_CODE_URL_DEFAULT,
        help="Override the device code endpoint if necessary",
    )
    parser.add_argument(
        "--output",
        help="Optional path to store the full response + code verifier as JSON",
    )

    args = parser.parse_args()

    try:
        data = request_device_code(args.client_id, args.scopes, args.device_code_url)
    except requests.HTTPError as exc:  # pragma: no cover - safety net for CLI users
        print(f"Request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # pragma: no cover - safety net for CLI users
        print(f"Unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fptr:
            json.dump(data, fptr, indent=2)
            fptr.write("\n")

    _print_summary(data)


if __name__ == "__main__":
    main()
