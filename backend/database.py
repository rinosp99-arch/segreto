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

# Collections (legacy)
models_col = db['models']
categories_col = db['categories']
articles_col = db['articles']
events_col = db['analytics_events']
admins_col = db['admin_users']
settings_col = db['settings']
audit_col = db['audit_logs']
files_col = db['files']

# Collections (SUPER API v1)
api_keys_col = db['api_keys']
versions_col = db['versions']
idempotency_col = db['idempotency_keys']
seo_issues_col = db['seo_issues']
redirects_col = db['redirects']
landings_col = db['landings']
experiments_col = db['experiments']
exposures_col = db['experiment_exposures']
health_col = db['health_checks']
alerts_col = db['alerts']
jobs_col = db['jobs']
job_runs_col = db['job_runs']
config_col = db['config']
webhooks_col = db['webhooks']
webhook_deliveries_col = db['webhook_deliveries']
backups_col = db['backups']
ai_actions_col = db['ai_actions']
analytics_daily_col = db['analytics_daily']


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
    await events_col.create_index([('event', 1), ('timestamp', -1)])
    await events_col.create_index('geo.country')
    await events_col.create_index('session_id')
    # v1
    await api_keys_col.create_index('key_hash', unique=True)
    await versions_col.create_index([('entity', 1), ('entity_id', 1), ('timestamp', -1)])
    await versions_col.create_index('request_id')
    await idempotency_col.create_index('created_dt', expireAfterSeconds=60 * 60 * 24)
    await idempotency_col.create_index([('key', 1), ('principal', 1), ('path', 1)], unique=True)
    await seo_issues_col.create_index([('entity_type', 1), ('entity_id', 1), ('code', 1), ('field', 1)], unique=True)
    await seo_issues_col.create_index('status')
    await redirects_col.create_index('from_path', unique=True)
    await landings_col.create_index('slug', unique=True)
    await experiments_col.create_index('stato')
    await exposures_col.create_index([('experiment_id', 1), ('session_id', 1)], unique=True)
    await alerts_col.create_index([('stato', 1), ('created_at', -1)])
    await alerts_col.create_index('dedupe_key')
    await jobs_col.create_index('name', unique=True)
    await job_runs_col.create_index([('job', 1), ('started_at', -1)])
    await webhook_deliveries_col.create_index('created_at')
    await ai_actions_col.create_index('timestamp')
    await analytics_daily_col.create_index([('giorno', 1), ('model_id', 1), ('country', 1)], unique=True)
    await files_col.create_index('id', unique=True, sparse=True)
    await files_col.create_index('storage_path')
