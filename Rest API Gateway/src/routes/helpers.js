// Shared helpers for control routes: input validation, controller resolution,
// and dispatching a framed message onto the right connection.

const { config } = require('../config');
const { ensureConnection } = require('../connectionManager');
const { ApiError } = require('../middleware/errors');
const { maskForLine, validateLine } = require('../edidio/lineTypes');

// --- Validation ------------------------------------------------------------

// Parse and range-check an integer field. Throws ApiError(400) on any problem.
function int(value, name, { min = -Infinity, max = Infinity, required = true, def } = {}) {
	if (value === undefined || value === null || value === '') {
		if (required) throw new ApiError(400, `Missing required field: ${name}`);
		return def;
	}
	const n = Number(value);
	if (!Number.isInteger(n)) throw new ApiError(400, `${name} must be an integer`);
	if (n < min || n > max) throw new ApiError(400, `${name} must be between ${min} and ${max}`);
	return n;
}

// Parse an array of 0-255 byte levels (for DMX). Accepts a JSON array.
function byteArray(value, name) {
	if (!Array.isArray(value) || value.length === 0) {
		throw new ApiError(400, `${name} must be a non-empty array of 0-255 values`);
	}
	return value.map((v, i) => int(v, `${name}[${i}]`, { min: 0, max: 255 }));
}

// --- Controller resolution -------------------------------------------------

// Resolve the target controller from the request. Precedence:
//   body.controller / query.controller  ->  EDIDIO_IP default.
// Optional per-request `useTLS` / `port` overrides are read from the same source.
function resolveTarget(req) {
	const src = { ...req.query, ...req.body };
	const ip = src.controller || config.defaultControllerIp;
	if (!ip) {
		throw new ApiError(
			400,
			'No controller specified. Provide `controller` (IP) in the request or set EDIDIO_IP.',
		);
	}
	const options = {};
	if (src.useTLS !== undefined) options.useTLS = /^(1|true|yes|on)$/i.test(String(src.useTLS));
	if (src.port !== undefined) options.port = int(src.port, 'port', { min: 1, max: 65535 });
	return { ip, options };
}

// Ensure a line number is valid for the expected protocol given what discovery
// told us about the controller (skipped when line types are unknown).
function assertLineType(conn, line, expected) {
	const check = validateLine(conn.lineTypes, line, expected);
	if (!check.ok) throw new ApiError(409, check.reason);
}

// --- Dispatch --------------------------------------------------------------

// Ensure a connection to the resolved controller and write one framed message.
// `buildFrame(conn)` returns the Uint8Array to send (given the live connection,
// so it can consult lineTypes). Returns a normalized success payload.
async function dispatch(req, expected, buildFrame) {
	const { ip, options } = resolveTarget(req);
	const { conn, connected } = await ensureConnection(ip, options);

	if (!connected || !conn.connected) {
		throw new ApiError(
			503,
			`Controller ${ip} is not connected. The gateway is retrying in the background; try again shortly.`,
		);
	}

	const frame = buildFrame(conn);
	const sent = await conn.send(frame);
	if (!sent) throw new ApiError(503, `Controller ${ip} dropped before the message could be sent.`);

	return { ok: true, controller: ip, connected: true };
}

module.exports = { int, byteArray, resolveTarget, assertLineType, dispatch, maskForLine };
