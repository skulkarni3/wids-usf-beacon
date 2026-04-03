from fastapi import FastAPI

from app.routes import auth_api
from app.routes import chatbot_api
from app.routes import checklist_api
from app.routes import maps_api
from app.routes import monitor_api
from app.routes import onboarding_api
from app.routes import translate_api

app = FastAPI(title = "Watch Duty Data Exploration")

app.include_router(auth_api.router)
app.include_router(chatbot_api.router)
app.include_router(checklist_api.router)
app.include_router(maps_api.router)
app.include_router(monitor_api.router)
app.include_router(onboarding_api.router)
app.include_router(translate_api.router)
