// Only VITE_-prefixed values are ever read here — they are baked into the
// browser bundle and are not secrets themselves (base URLs only). Never
// add a WAHA API key, INTERNAL_SERVICE_KEY, or any other server-side
// credential to this file or to any VITE_ variable — see
// docs/06-SECURITY.md and frontend/.env.example.
export const config = {
  bffBaseUrl: import.meta.env.VITE_BFF_BASE_URL ?? '',
  djangoBaseUrl: import.meta.env.VITE_DJANGO_BASE_URL ?? '',
  wahaSessionName: import.meta.env.VITE_WAHA_SESSION_NAME ?? '',
};
