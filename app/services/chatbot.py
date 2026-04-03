import os
import json
from datetime import datetime
from pathlib import Path
import anthropic
import pytz
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape
from timezonefinder import TimezoneFinder

_tf = TimezoneFinder()

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
# app/services/chatbot.py -> app/prompts
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_jinja_env = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR / "templates")),
    autoescape=select_autoescape(disabled_extensions=("jinja",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _read_prompt_file(*parts: str) -> str:
    path = PROMPTS_DIR.joinpath(*parts)
    return path.read_text(encoding="utf-8").strip()


def _load_few_shot_examples(filename: str) -> list[dict]:
    path = PROMPTS_DIR / "few_shot" / filename
    return json.loads(path.read_text(encoding="utf-8"))


def _render_template(template_name: str, context: dict) -> str:
    template = _jinja_env.get_template(template_name)
    return template.render(**context).strip()


def build_system_prompt(location, evac_data, maps_data, language="auto", no_route=False, distance=50000, timestamp=None, memories: str = ""):
    """Builds the system prompt using all input data."""

    language_rule = "Detect the user's language from their most recent message and always reply in that same language. Ignore the language of earlier messages in the conversation."

    dist_km = round(distance / 1000)

    if no_route:
        fire_section = (
            f"Active Evacuation Zones : {len(evac_data)} zone(s) found within {dist_km} km of the user's location.\n"
            f"Most Recent Update      : {evac_data[0].get('date_modified', 'unknown')}\n"
            "Urgency                 : CRITICAL — no safe evacuation route could be calculated.\n"
            "Action Required         : Tell the user to call 911 immediately and follow emergency services instructions."
        ) if evac_data else (
            "Active Evacuation Zones : None detected, but no safe route could be calculated.\n"
            "Urgency                 : CRITICAL — road conditions or fire risk may block all exits.\n"
            "Action Required         : Tell the user to call 911 immediately."
        )
    elif evac_data:
        n = len(evac_data)
        fire_section = (
            f"Active Evacuation Zones : {n} zone(s) found within {dist_km} km of the user's location.\n"
            f"Most Recent Update      : {evac_data[0].get('date_modified', 'unknown')}\n"
            "Urgency                 : HIGH — evacuation zones are active nearby."
        )
    else:
        fire_section = (
            f"Active Evacuation Zones : None found within {dist_km} km of the user's location.\n"
            "Urgency                 : LOW — no active evacuation zones detected."
        )

    route_section = (
        "Evacuation Route: A route has been calculated and loaded on the map tab."
        if maps_data else
        "Evacuation Route: Not yet calculated."
    )

    coords = (
        f"{location['lat']:.4f}, {location['lon']:.4f}" if location else "unknown"
    )
    if timestamp and location:
        tz_name = _tf.timezone_at(lat=location["lat"], lng=location["lon"])
        if tz_name:
            local_tz = pytz.timezone(tz_name)
            local_dt = pytz.utc.localize(timestamp).astimezone(local_tz)
            ts_display = local_dt.strftime("%Y-%m-%d %H:%M %Z")
        else:
            ts_display = timestamp.strftime("%Y-%m-%d %H:%M UTC")
    elif timestamp:
        ts_display = timestamp.strftime("%Y-%m-%d %H:%M UTC")
    else:
        ts_display = datetime.now().strftime("%Y-%m-%d %H:%M")
    shared_context = {
        "timestamp_display": ts_display,
        "location_display": location["display"] if location else "Unknown",
        "coordinates": coords,
        "fire_section": fire_section,
        "route_section": route_section,
        "language_rule": language_rule,
    }

    beacon_core = _read_prompt_file("system", "beacon_core.txt")
    safety_rules = _read_prompt_file("system", "safety_rules.txt")
    tool_descriptions = _read_prompt_file("system", "tool_descriptions.txt")
    sos_protocols = _read_prompt_file("system", "sos_protocols.txt")

    user_context = _render_template("user_context.jinja", shared_context)
    checklist_context = _render_template("checklist_context.jinja", shared_context)

    evacuation_examples = _load_few_shot_examples("evacuation_examples.json")
    refusal_examples = _load_few_shot_examples("refusal_examples.json")

    evac_example_text = "\n".join(
        f"- User: {ex['user']}\n  Assistant: {ex['assistant']}" for ex in evacuation_examples
    )
    refusal_example_text = "\n".join(
        f"- User: {ex['user']}\n  Assistant: {ex['assistant']}" for ex in refusal_examples
    )

    memory_block = (
        f"== WHAT I KNOW ABOUT THIS USER ==\n{memories}\n\n"
        if memories and memories.strip() else ""
    )

    return (
        f"{beacon_core}\n\n"
        f"{safety_rules}\n\n"
        f"{sos_protocols}\n\n"
        f"{tool_descriptions}\n\n"
        f"{memory_block}"
        f"{user_context}\n\n"
        f"{checklist_context}\n\n"
        "== FEW-SHOT EXAMPLES (GOOD EVAC RESPONSES) ==\n"
        f"{evac_example_text}\n\n"
        "== FEW-SHOT EXAMPLES (SAFE REFUSALS) ==\n"
        f"{refusal_example_text}"
    )


def run_chat(location, evac_data, maps_data):
    """Runs the main chat loop."""

    system_prompt = build_system_prompt(location, evac_data, maps_data)
    conversation_history = []

    n = len(evac_data) if evac_data else 0
    print(f"\nWildfire Assistant | Evac Zones Nearby: {n} | {location['display']}")
    print("Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() == "quit":
            break
        if not user_input:
            continue

        conversation_history.append({"role": "user",
                                     "content": user_input})

        response = client.messages.create(
            model=os.getenv(ANTHROPIC_LLM_MODEL),
            max_tokens=os.getenv(ANTHROPIC_MAX_TOKENS),
            system=system_prompt,
            messages=conversation_history
        )
  
        reply = response.content[0].text
        conversation_history.append({"role": "assistant",
                                     "content": reply})