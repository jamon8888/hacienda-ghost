import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Request
from keyshield import ApiKeyService
from keyshield.api import create_depends_api_key
from keyshield.hasher.argon2 import Argon2ApiKeyHasher
from keyshield.repositories.in_memory import InMemoryApiKeyRepository


load_dotenv()
pepper = os.getenv("SECRET_PEPPER")
hasher = Argon2ApiKeyHasher(pepper=pepper)

path = Path(__file__).parent / "db.sqlite3"
database_url = os.environ.get("DATABASE_URL", f"sqlite+aiosqlite:///{path}")

repo = InMemoryApiKeyRepository()
svc = ApiKeyService(repo=repo, hasher=hasher)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager to handle application startup and shutdown events."""
    # Startup event
    await svc.load_dotenv()
    app.state.svc_api_keys = svc
    yield
    # Shutdown event


async def get_svc_api_keys(request: Request) -> ApiKeyService:
    """Dependency to inject the API key service with an active SQLAlchemy async session."""
    return request.app.state.svc_api_keys


security = create_depends_api_key(get_svc_api_keys)
app = FastAPI(
    lifespan=lifespan,
    # dependencies=[Depends(security)],
)
