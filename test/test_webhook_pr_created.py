#!/usr/bin/env python3
"""
Test script to post a simulated GitHub 'pull_request' (opened) webhook event
to the deployed Webhook Service in Google Cloud Run (or a local server).
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path and load environment variables
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

try:
    import httpx
except ImportError:
    print("❌ httpx module not found. Please run via 'uv run python test/test_webhook_pr_created.py'")
    sys.exit(1)


DEFAULT_SERVICE_URL = "https://github-webhook-service-keqxuru5ha-uc.a.run.app"


def build_pr_event_payload(repo_name: str, pr_number: int, pr_title: str, action: str = "opened") -> dict:
    """Build a realistic GitHub pull_request webhook JSON payload."""
    return {
        "action": action,
        "number": pr_number,
        "repository": {
            "full_name": repo_name,
            "name": repo_name.split("/")[-1] if "/" in repo_name else repo_name,
            "owner": {
                "login": repo_name.split("/")[0] if "/" in repo_name else "owner",
                "type": "User"
            },
            "html_url": f"https://github.com/{repo_name}"
        },
        "pull_request": {
            "number": pr_number,
            "title": pr_title,
            "body": "This is a simulated Pull Request created by the automated GCP webhook test script.",
            "state": "open",
            "locked": False,
            "user": {
                "login": "automated-tester",
                "type": "User"
            },
            "html_url": f"https://github.com/{repo_name}/pull/{pr_number}",
            "diff_url": f"https://github.com/{repo_name}/pull/{pr_number}.diff",
            "patch_url": f"https://github.com/{repo_name}/pull/{pr_number}.patch",
            "head": {
                "label": f"{repo_name.split('/')[0]}:feature/test-pr-{pr_number}",
                "ref": f"feature/test-pr-{pr_number}",
                "sha": "6dcb09b5b57875f334f61aebed695e2e4193db5e"
            },
            "base": {
                "label": f"{repo_name.split('/')[0]}:main",
                "ref": "main",
                "sha": "9b1c20e2343828989a3df7beebfdfcbb8268ecbd"
            },
            "merged": False,
            "mergeable": True
        },
        "sender": {
            "login": "automated-tester",
            "type": "User"
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Send a GitHub pull_request webhook event to the GCP Webhook Service.")
    
    # Determine default repository from ALLOWED_CODE_REPOS environment variable if set
    default_repo = os.getenv("ALLOWED_CODE_REPOS", "hning86/gcp-scratch").split(",")[0].strip()
    default_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()

    parser.add_argument("--url", default=DEFAULT_SERVICE_URL, help=f"Target Webhook Service URL (default: {DEFAULT_SERVICE_URL})")
    parser.add_argument("--repo", default=default_repo, help=f"Repository full name (default: {default_repo})")
    parser.add_argument("--pr", type=int, default=1, help="Pull Request number (default: 1)")
    parser.add_argument("--title", default="Test PR from automated webhook test script", help="Pull Request title")
    parser.add_argument("--action", default="opened", choices=["opened", "synchronize", "closed"], help="PR action type (default: opened)")
    parser.add_argument("--secret", default=default_secret, help="HMAC webhook secret for signing (defaults to GITHUB_WEBHOOK_SECRET in .env)")
    
    args = parser.parse_args()

    target_url = args.url.rstrip("/")
    if not target_url.endswith("/webhook/github"):
        target_url = f"{target_url}/webhook/github"

    print("============================================================")
    print(" 🚀 GitHub PR Webhook Event Tester")
    print("============================================================")
    print(f"Target Endpoint:  {target_url}")
    print(f"Repository:       {args.repo}")
    print(f"PR Number:        #{args.pr}")
    print(f"PR Title:         '{args.title}'")
    print(f"Action:           {args.action}")
    print(f"Signing Secret:   {'✅ Present' if args.secret else '⚠️ Not configured'}")
    print("============================================================")

    # 1. Build payload and encode to bytes
    payload_dict = build_pr_event_payload(args.repo, args.pr, args.title, action=args.action)
    payload_bytes = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")

    # 2. Prepare GitHub webhook headers
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": f"test-delivery-{args.repo.replace('/', '-')}-pr-{args.pr}",
        "User-Agent": "GitHub-Hookshot/test-script"
    }

    # 3. Calculate HMAC SHA-256 signature if secret is provided
    if args.secret:
        mac = hmac.new(args.secret.encode("utf-8"), msg=payload_bytes, digestmod=hashlib.sha256)
        headers["X-Hub-Signature-256"] = f"sha256={mac.hexdigest()}"

    # 4. Send POST request
    print(f"\nSending POST request to {target_url}...")
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(target_url, content=payload_bytes, headers=headers)
            
        print("\n📥 Response Received:")
        print(f"Status Code: {response.status_code} {response.reason_phrase}")
        try:
            resp_json = response.json()
            print("Response Body:")
            print(json.dumps(resp_json, indent=2))
        except json.JSONDecodeError:
            print("Response Body (Text):")
            print(response.text)

        if response.status_code == 200:
            print("\n✅ Webhook event successfully posted and accepted by the service!")
        else:
            print(f"\n❌ Webhook delivery failed with HTTP {response.status_code}.")
            sys.exit(1)
            
    except httpx.RequestError as e:
        print(f"\n❌ Network error while sending request: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
