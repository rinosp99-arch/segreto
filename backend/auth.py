import os
import time
import jwt
import bcrypt
from datetime import datetime, timezone, timedelta
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret-change')
JWT_ALG = 'HS256'
JWT_EXPIRE_HOURS = int(os.environ.get('JWT_EXPIRE_HOURS', '12'))

security = HTTPBearer(auto_error=False)

# --- password hashing (bcrypt directly, avoids passlib version pitfalls) ---

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def _role_of(ruolo: str) -> str:
    r = (ruolo or '').upper()
    if r in ('AMMINISTRATORE', 'ADMINISTRATOR', ''):
        return 'SUPER_ADMIN'
    return r


def create_token(sub: str, email: str, ruolo: str = 'amministratore') -> str:
    payload = {
        'sub': sub,
        'email': email,
        'ruolo': ruolo,
        'role': _role_of(ruolo),
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None


async def get_current_admin(creds: HTTPAuthorizationCredentials = Depends(security)):
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail='Autenticazione richiesta')
    payload = decode_token(creds.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail='Sessione non valida o scaduta')
    return payload


# --- simple in-memory login rate limiter (per IP) ---
_login_attempts = {}
MAX_ATTEMPTS = 8
WINDOW_SECONDS = 300


def check_rate_limit(ip: str):
    now = time.time()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < WINDOW_SECONDS]
    if len(attempts) >= MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail='Troppi tentativi di accesso. Riprova tra qualche minuto.')
    attempts.append(now)
    _login_attempts[ip] = attempts


def reset_rate_limit(ip: str):
    _login_attempts.pop(ip, None)
