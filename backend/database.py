import os
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Collections
models_col = db['models']
categories_col = db['categories']
articles_col = db['articles']
events_col = db['analytics_events']
admins_col = db['admin_users']
settings_col = db['settings']
audit_col = db['audit_logs']
files_col = db['files']


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def serialize_doc(doc):
    """Recursively make a Mongo document JSON-serializable.
    Removes _id, converts datetimes to iso strings.
    """
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(d) for d in doc]
    if isinstance(doc, dict):
        out = {}
        for k, v in doc.items():
            if k == '_id':
                continue
            out[k] = serialize_doc(v)
        return out
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc


async def ensure_indexes():
    await models_col.create_index('slug', unique=True)
    await models_col.create_index('stato')
    await models_col.create_index('ordine')
    await categories_col.create_index('slug', unique=True)
    await articles_col.create_index('slug', unique=True)
    await admins_col.create_index('email', unique=True)
    await events_col.create_index('timestamp')
    await events_col.create_index('model_id')
    await events_col.create_index('tipo')
