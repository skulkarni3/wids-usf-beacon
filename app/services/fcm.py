import json
import os

import anthropic
import requests
from dotenv import load_dotenv
from typing import Optional
from google.auth.transport.requests import Request
from google.oauth2 import service_account

load_dotenv()

_FCM_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]
_creds: Optional[service_account.Credentials] = None


def _get_credentials() -> service_account.Credentials:
    global _creds
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if _creds is None:
        _creds = service_account.Credentials.from_service_account_file(
            cred_path, scopes=_FCM_SCOPES
        )
    if not _creds.valid:
        _creds.refresh(Request())
    return _creds


def _project_id() -> str:
    """Return project ID from env var, falling back to the service account JSON."""
    pid = os.getenv("GOOGLE_CLOUD_PROJECT")
    if pid:
        return pid
    import json
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    with open(cred_path) as f:
        return json.load(f).get("project_id", "")


def send_alert(device_token: str, title: str, body: str) -> str:
    """Send a push notification to a single device. Returns the FCM message ID."""
    project_id = _project_id()
    creds = _get_credentials()
    token = device_token.strip()

    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    print(f"[FCM] POST {url}  project={project_id}")

    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        },
        json={
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
            }
        },
    )
    if not resp.ok:
        print(f"[FCM] Error {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    msg_name = resp.json().get("name", "")
    print(f"[FCM] Sent OK — message: {msg_name}")
    return msg_name


def _translate_notification(title: str, body: str, language: str) -> tuple[str, str]:
    """Translate notification title and body via Claude. Returns (title, body) unchanged on error."""
    if not language or language == "en":
        return title, body
    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("ANTHROPIC_LLM_MODEL")
    client = anthropic.Anthropic(api_key=api_key)
    strings_json = json.dumps([title, body], ensure_ascii=False)
    prompt = (
        f"Translate the following JSON array of English strings into {language} "
        f"(ISO 639-1 code). Return ONLY a valid JSON object where each key is the "
        f"original English string and each value is the translation. No explanation.\n\n"
        f"{strings_json}"
    )
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        translations: dict = json.loads(raw)
        return translations.get(title, title), translations.get(body, body)
    except Exception as e:
        print(f"[FCM] Translation failed ({language}): {e}")
        return title, body


def send_fire_danger_alert(device_token: str, language: str = "en") -> str:
    title, body = _translate_notification(
        "Fire Danger Alert",
        "Fire danger detected near your location. Open Beacon and review your checklist and evacuation route.",
        language,
    )
    return send_alert(device_token, title=title, body=body)


def send_evac_alert(device_token: str, alert_type: str, language: str = "en") -> str:
    title, body = _translate_notification(
        "Evacuation Zone Alert",
        f"Your location is currently under evacuation {alert_type}. Open Beacon and review your checklist and evacuation route.",
        language,
    )
    return send_alert(device_token, title=title, body=body)


def send_no_route_alert(device_token: str, language: str = "en") -> str:
    title, body = _translate_notification(
        "CRITICAL: No Evacuation Route Available",
        "No safe evacuation route was found near you. Call 911 immediately and follow emergency services instructions.",
        language,
    )
    return send_alert(device_token, title=title, body=body)
