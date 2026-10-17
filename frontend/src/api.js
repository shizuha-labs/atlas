export function libraryHref(search) {
  if (typeof search === 'string' && /^\?[\w&=%+.\-~]*$/.test(search)) {
    return `/atlas/${search}`
  }
  return '/atlas/'
}

export function backToLibrary(stateSearch) {
  if (typeof stateSearch === 'string') return libraryHref(stateSearch)
  try {
    return libraryHref(sessionStorage.getItem('atlas-library') || '')
  } catch {
    return '/atlas/'
  }
}

export function rememberLibrary(search) {
  try {
    sessionStorage.setItem('atlas-library', typeof search === 'string' ? search : '')
  } catch {
    /* private mode can refuse storage; the link state still carries the filter */
  }
}

export function accessToken() {
  return localStorage.getItem('shizuha_access_token') || ''
}

let authModePromise

export function authMode() {
  if (!authModePromise) {
    authModePromise = fetch('/atlas/api/auth')
      .then(response => (response.ok ? response.json() : { mode: 'platform' }))
      .catch(() => ({ mode: 'platform' }))
  }
  return authModePromise
}

export function signIn() {
  const here = `${window.location.pathname}${window.location.search}`
  window.location.assign(`/id/login?continue=${encodeURIComponent(here)}`)
}

export async function loadOrganizations() {
  const mode = await authMode()
  if (mode.mode === 'local') {
    return [{ id: String(mode.organization_id || '1'), name: mode.organization_name || 'Local' }]
  }
  const token = accessToken()
  if (!token) return []
  try {
    const response = await fetch('/admin/api/organizations/', {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) return []
    const payload = await response.json()
    const rows = Array.isArray(payload) ? payload : (payload.results || [])
    return rows
      .filter(org => org && org.id != null)
      .map(org => ({ id: String(org.id), name: org.name || `Workspace ${org.id}` }))
  } catch {
    return []
  }
}

export async function atlasApi(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  const token = accessToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body) headers['Content-Type'] = 'application/json'
  const response = await fetch(`/atlas/api${path}`, { ...options, headers })
  if (response.status === 401) {
    const mode = await authMode()
    if (mode.mode !== 'local') signIn()
    const error = new Error(mode.mode === 'local' ? 'Sign in to this Atlas.' : 'Sign in with Shizuha ID.')
    error.local = mode.mode === 'local'
    throw error
  }
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = new Error(payload.detail || 'Atlas could not complete that request.')
    error.status = response.status
    throw error
  }
  return payload
}
