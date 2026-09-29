// Shared-secret API-key gate.
//
// Two keys:
//   EDIDIO_API_KEY       full control (any method)
//   EDIDIO_READ_API_KEY  read-only: GET/HEAD only (status, state, live events)
// Keys are sent as `X-API-Key` or `Authorization: Bearer <key>`. Browsers'
// EventSource can't set headers, so GET requests may also pass `?api_key=`.
//
// With no keys configured, auth is disabled — and server.js refuses to bind to a
// non-loopback address unless EDIDIO_ALLOW_UNAUTHENTICATED=true.

const crypto = require('node:crypto');
const { config } = require('../config');
const { ApiError } = require('./errors');

const READ_METHODS = new Set(['GET', 'HEAD']);
const LOOPBACK = new Set(['127.0.0.1', '::1', 'localhost']);

function extractKey(req) {
	const header = req.get('x-api-key');
	if (header) return header.trim();
	const auth = req.get('authorization');
	if (auth && /^bearer\s+/i.test(auth)) return auth.replace(/^bearer\s+/i, '').trim();
	if (READ_METHODS.has(req.method) && typeof req.query.api_key === 'string') return req.query.api_key;
	return null;
}

// Constant-time comparison so response timing doesn't leak the key.
function safeEqual(a, b) {
	if (!a || !b) return false;
	const ha = crypto.createHash('sha256').update(String(a)).digest();
	const hb = crypto.createHash('sha256').update(String(b)).digest();
	return crypto.timingSafeEqual(ha, hb);
}

function apiKeyAuth(req, res, next) {
	if (!config.apiKey && !config.readApiKey) return next(); // auth disabled
	const provided = extractKey(req);
	if (safeEqual(provided, config.apiKey)) {
		req.access = 'control';
		return next();
	}
	if (safeEqual(provided, config.readApiKey)) {
		if (!READ_METHODS.has(req.method)) {
			return next(new ApiError(403, 'This API key is read-only.'));
		}
		req.access = 'read';
		return next();
	}
	next(new ApiError(401, 'Missing or invalid API key.'));
}

// Returns an error message if the configuration is unsafe to start, else null.
function startupSecurityError(cfg = config) {
	if (cfg.apiKey || cfg.readApiKey || cfg.allowUnauthenticated) return null;
	if (LOOPBACK.has(cfg.host)) return null;
	return (
		`Refusing to listen on ${cfg.host} without an API key. Set EDIDIO_API_KEY ` +
		'(recommended), bind HOST=127.0.0.1, or set EDIDIO_ALLOW_UNAUTHENTICATED=true ' +
		'on a trusted, isolated network.'
	);
}

module.exports = { apiKeyAuth, startupSecurityError, safeEqual };
