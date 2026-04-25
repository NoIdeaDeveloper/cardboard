/**
 * Cardboard API client
 * Communicates with the FastAPI backend.
 */

const API_BASE = '/api';

// Response cache: stores { etag, data, headers } per GET path so that a 304
// reply can be resolved from the body we saw the last time the ETag changed.
// Headers are snapshotted into a fresh Headers instance so later fetches can't
// mutate cached values out from under us.
const _cache = {};

// Call after any mutation that changes the collection so the next GET fetches fresh data
function invalidateCollectionEtag() {
  for (const key of Object.keys(_cache)) {
    if (key === '/games/' || key.startsWith('/games/?') || key === '/collection/stats') {
      delete _cache[key];
    }
  }
}

async function request(method, path, body = null) {
  const opts = { method, headers: {} };
  if (body !== null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (method === 'GET' && _cache[path]) {
    opts.headers['If-None-Match'] = _cache[path].etag;
  }

  const resp = await fetch(`${API_BASE}${path}`, opts);

  if (resp.status === 304) {
    const cached = _cache[path];
    return cached ? cached.data : null;
  }
  if (resp.status === 204) return null;

  const data = await resp.json().catch(() => ({ detail: resp.statusText }));

  if (!resp.ok) {
    const msg = data.detail || `HTTP ${resp.status}`;
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = resp.status;
    throw err;
  }

  const etag = resp.headers.get('ETag');
  if (etag && method === 'GET') {
    _cache[path] = { etag, data, headers: new Headers(resp.headers) };
  }

  return data;
}

// Like request() but also returns response headers for endpoints that expose metadata.
async function requestWithMeta(method, path, body = null) {
  const opts = { method, headers: {} };
  if (body !== null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (method === 'GET' && _cache[path]) {
    opts.headers['If-None-Match'] = _cache[path].etag;
  }

  const resp = await fetch(`${API_BASE}${path}`, opts);

  if (resp.status === 304) {
    const cached = _cache[path];
    if (cached) return { data: cached.data, headers: cached.headers };
    return { data: null, headers: resp.headers };
  }
  if (resp.status === 204) return { data: null, headers: resp.headers };

  const data = await resp.json().catch(() => ({ detail: resp.statusText }));

  if (!resp.ok) {
    const msg = data.detail || `HTTP ${resp.status}`;
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = resp.status;
    throw err;
  }

  const etag = resp.headers.get('ETag');
  if (etag && method === 'GET') {
    _cache[path] = { etag, data, headers: new Headers(resp.headers) };
  }

  return { data, headers: resp.headers };
}

async function uploadFile(path, file) {
  const fd = new FormData();
  fd.append('file', file);
  const resp = await fetch(`${API_BASE}${path}`, { method: 'POST', body: fd });
  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => ({ detail: resp.statusText }));
  if (!resp.ok) {
    const err = new Error(data.detail || `HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return data;
}

function _triggerDownload(url) {
  const a = document.createElement('a');
  a.href = url; a.download = '';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

const API = {
  // Games
  // Returns { data: GameResponse[], total: number } where total is the full matched count
  getGames: async (params = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== ''));
    const path = `/games/${qs.toString() ? '?' + qs : ''}`;
    const { data, headers } = await requestWithMeta('GET', path);
    const total = parseInt(headers.get('X-Total-Count') || '0', 10);
    return { data, total };
  },
  getGame:    (id)       => request('GET',    `/games/${id}`),
  getSimilarGames: (id) => request('GET',    `/games/${id}/similar`),
  createGame: (data)     => request('POST',   '/games/', data),
  updateGame: (id, data) => request('PATCH',  `/games/${id}`, data),
  deleteGame: (id)       => request('DELETE', `/games/${id}`),

  // Play sessions
  getSessions:   (gameId)       => request('GET',    `/games/${gameId}/sessions`),
  addSession:    (gameId, data) => request('POST',   `/games/${gameId}/sessions`, data),
  updateSession: (id, data)     => request('PATCH',  `/sessions/${id}`, data),
  deleteSession: (id)           => request('DELETE', `/sessions/${id}`),

  // Images
  uploadImage:        (gameId, file) => uploadFile(`/games/${gameId}/image`, file),
  deleteImage:        (gameId)       => request('DELETE', `/games/${gameId}/image`),

  // Instructions
  uploadInstructions: (gameId, file) => uploadFile(`/games/${gameId}/instructions`, file),
  deleteInstructions: (gameId)       => request('DELETE', `/games/${gameId}/instructions`),

  // Photo gallery (multi-image)
  getImages:          (gameId)           => request('GET', `/games/${gameId}/images`),
  uploadGalleryImage: (gameId, file)     => uploadFile(`/games/${gameId}/images`, file),
  deleteGalleryImage: (gameId, imgId)    => request('DELETE', `/games/${gameId}/images/${imgId}`),
  reorderGalleryImages: (gameId, order)  => request('PATCH', `/games/${gameId}/images/reorder`, { order }),
  addGalleryImageFromUrl: (gameId, url)  => request('POST',  `/games/${gameId}/images/from-url`, { url }),
  updateGalleryImage:     (gameId, imgId, data) => request('PATCH', `/games/${gameId}/images/${imgId}`, data),

  // Stats
  getStats: () => request('GET', '/stats'),
  getCollectionStats: () => request('GET', '/collection/stats'),

  // ETag cache management
  invalidateCollectionEtag,

  // BGG search / fetch (for Add Game autocomplete)
  bggSearch:  (q)       => request('GET', `/games/bgg-search?q=${encodeURIComponent(q)}`),
  bggFetch:   (bggId)   => request('GET', `/games/bgg-fetch/${bggId}`),

  // BGG import
  importBGG: (file) => uploadFile('/games/import/bgg', file),

  // BGG refresh
  refreshFromBGG: (gameId) => request('POST', `/games/${gameId}/refresh-bgg`),

  // BGG play history import
  importBGGPlays: (file) => uploadFile('/games/import/bgg-plays', file),

  // CSV import
  importCSV: (file) => uploadFile('/games/import/csv', file),

  // Game night suggestions
  suggestGames: (playerCount, maxMinutes) => request('POST', '/games/suggest', { player_count: playerCount, max_minutes: maxMinutes }),

  // Players
  getPlayers:         ()           => request('GET',    '/players/'),
  createPlayer:       (name)       => request('POST',   '/players/', { name }),
  renamePlayer:       (id, name)   => request('PATCH',  `/players/${id}`, { name }),
  deletePlayer:       (id)         => request('DELETE', `/players/${id}`),
  getPlayerStats:     (id)         => request('GET',    `/players/${id}/stats`),
  uploadPlayerAvatar:    (id, file)   => uploadFile(`/players/${id}/avatar`, file),
  setPlayerAvatarPreset: (id, preset) => request('POST', `/players/${id}/avatar/preset`, { preset }),
  deletePlayerAvatar:    (id)         => request('DELETE', `/players/${id}/avatar`),

  // Collection sharing
  getShareTokens:    ()              => request('GET',    '/share/tokens'),
  createShareToken:  (label, expiresIn) => {
    const params = new URLSearchParams();
    if (label) params.set('label', label);
    if (expiresIn) params.set('expires_in', expiresIn);
    const qs = params.toString();
    return request('POST', `/share/tokens${qs ? '?' + qs : ''}`);
  },
  deleteShareToken:  (token)         => request('DELETE', `/share/tokens/${token}`),
  getSharedGames:    (token)         => request('GET',    `/share/${token}/games`),
  getSharedGame:     (token, gameId) => request('GET',    `/share/${token}/games/${gameId}`),
  submitWantToPlay:  (token, gameId, data) => request('POST', `/share/${token}/games/${gameId}/want-to-play`, data),
  getWantToPlayRequests: ()          => request('GET',    '/share/requests'),
  markRequestSeen:   (id)            => request('PATCH',  `/share/requests/${id}/seen`),

  // Goals
  getGoals:    ()          => request('GET',    '/goals/'),
  createGoal:  (data)      => request('POST',   '/goals/', data),
  deleteGoal:  (id)        => request('DELETE', `/goals/${id}`),

  // Backup
  downloadBackup:     () => _triggerDownload(`${API_BASE}/games/backup`),
  downloadJsonBackup: () => _triggerDownload(`${API_BASE}/games/backup/json`),
  restoreBackup:      (file) => uploadFile('/games/restore', file),

  // Persistent user settings
  getSetting: (key)        => request('GET', `/settings/${encodeURIComponent(key)}`),
  setSetting: (key, value) => request('PUT', `/settings/${encodeURIComponent(key)}`, { value }),
};
