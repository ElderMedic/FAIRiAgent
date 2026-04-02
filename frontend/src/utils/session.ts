const SESSION_ID_STORAGE_KEY = 'fairiagent.webui.session.id';
const SESSION_STARTED_AT_STORAGE_KEY = 'fairiagent.webui.session.startedAt';

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export interface WebSession {
  id: string;
  startedAt: string;
}

function canUseBrowserStorage() {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

function isValidUuid(value: string | null | undefined): value is string {
  return Boolean(value && UUID_PATTERN.test(value));
}

function isValidIsoTimestamp(value: string | null | undefined): value is string {
  if (!value) return false;
  return !Number.isNaN(Date.parse(value));
}

function fallbackUuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const rand = Math.random() * 16 | 0;
    const value = char === 'x' ? rand : (rand & 0x3) | 0x8;
    return value.toString(16);
  });
}

function generateSession(): WebSession {
  const id =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : fallbackUuid();
  return {
    id,
    startedAt: new Date().toISOString(),
  };
}

function readSessionFromSearch(search?: string): WebSession | null {
  if (typeof URLSearchParams === 'undefined') return null;
  const params = new URLSearchParams(search ?? (typeof window !== 'undefined' ? window.location.search : ''));
  const id = params.get('session');
  if (!isValidUuid(id)) return null;
  const ts = params.get('ts');
  // Timestamp is optional — fall back to current time so UUID alone is sufficient
  const startedAt = isValidIsoTimestamp(ts) ? ts : new Date().toISOString();
  return { id, startedAt };
}

function readStoredSession(): WebSession | null {
  if (!canUseBrowserStorage()) return null;
  const id = window.localStorage.getItem(SESSION_ID_STORAGE_KEY);
  const startedAt = window.localStorage.getItem(SESSION_STARTED_AT_STORAGE_KEY);
  if (!isValidUuid(id) || !isValidIsoTimestamp(startedAt)) {
    return null;
  }
  return { id, startedAt };
}

function storeSession(session: WebSession) {
  if (!canUseBrowserStorage()) return;
  window.localStorage.setItem(SESSION_ID_STORAGE_KEY, session.id);
  window.localStorage.setItem(SESSION_STARTED_AT_STORAGE_KEY, session.startedAt);
}

export function isValidSessionId(value: string | null | undefined): value is string {
  return isValidUuid(value);
}

export function isValidSessionTimestamp(value: string | null | undefined): value is string {
  return isValidIsoTimestamp(value);
}

export function getWebSession(search?: string): WebSession {
  const fromSearch = readSessionFromSearch(search);
  if (fromSearch) {
    storeSession(fromSearch);
    return fromSearch;
  }

  const stored = readStoredSession();
  if (stored) {
    return stored;
  }

  const created = generateSession();
  storeSession(created);
  return created;
}

export function setWebSession(session: WebSession) {
  storeSession(session);
}

export function getSessionHeaders(search?: string): Record<string, string> {
  const session = getWebSession(search);
  return {
    'X-FAIRifier-Session-Id': session.id,
    'X-FAIRifier-Session-Started-At': session.startedAt,
  };
}

export function withSessionRouteSearch(search = ''): string {
  const session = getWebSession(search);
  const params = new URLSearchParams(search);
  params.set('session', session.id);
  params.set('ts', session.startedAt);
  const next = params.toString();
  return next ? `?${next}` : '';
}

export function withSessionApiPath(path: string): string {
  const session = getWebSession();
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}session_id=${encodeURIComponent(session.id)}&session_started_at=${encodeURIComponent(session.startedAt)}`;
}

export function buildAppRoute(pathname: string): string {
  return `${pathname}${withSessionRouteSearch()}`;
}

export function buildRouteWithSession(pathname: string, session: WebSession): string {
  const params = new URLSearchParams();
  params.set('session', session.id);
  params.set('ts', session.startedAt);
  return `${pathname}?${params.toString()}`;
}
