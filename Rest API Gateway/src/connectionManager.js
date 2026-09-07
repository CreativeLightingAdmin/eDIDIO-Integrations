// Pools one persistent ControllerConnection per controller IP.
//
// A REST gateway is long-lived and may drive several controllers, so we keep a
// warm, auto-reconnecting socket per IP rather than dialling on every request.
// The first control request for an unknown IP transparently opens a connection
// (using discovery to learn its line-type map and TLS capability where it can).

const { ControllerConnection } = require('./edidio/ControllerConnection');
const { discoverControllers } = require('./edidio/discovery');
const { config } = require('./config');

const connections = new Map(); // ip -> ControllerConnection

// Best-effort discovery lookup so we can enrich a connection with line types and
// learn whether the unit supports TLS. Never throws — a probe failure just means
// we connect with the caller's explicit options (or defaults).
async function probe(ip) {
	try {
		const found = await discoverControllers();
		return found.find((c) => c.IP === ip) || null;
	} catch {
		return null;
	}
}

// Open (or replace) a connection for `ip`. Resolves { conn, connected, error }.
// A failed initial TCP connect does NOT throw: the connection keeps retrying in
// the background, and callers can report the pending state.
//
// options: { port?, useTLS?, lineTypes? }
async function openConnection(ip, options = {}) {
	closeConnection(ip);

	let { useTLS, lineTypes, port } = options;
	const info = await probe(ip);
	if (info) {
		if (lineTypes === undefined && Array.isArray(info.LINES)) lineTypes = info.LINES;
		// Honour an explicit useTLS; otherwise adopt the controller's advertised
		// capability, falling back to the gateway default.
		if (useTLS === undefined && typeof info.TLS === 'boolean') useTLS = info.TLS;
	}
	if (useTLS === undefined) useTLS = config.defaultUseTLS;

	const conn = new ControllerConnection(ip, { port, useTLS, lineTypes });
	// Store before connecting so the background retry loop is always tracked and
	// closeConnection() can stop it even if the first attempt fails.
	connections.set(ip, conn);

	try {
		await conn.connect();
		return { conn, connected: true };
	} catch (error) {
		return { conn, connected: false, error };
	}
}

// Return an existing connection for `ip`, or open one on demand. Used by control
// routes so callers don't have to POST /controllers first.
async function ensureConnection(ip, options = {}) {
	const existing = connections.get(ip);
	if (existing) return { conn: existing, connected: existing.connected };
	return openConnection(ip, options);
}

function getConnection(ip) {
	return connections.get(ip) || null;
}

function listConnections() {
	return [...connections.entries()].map(([ip, conn]) => ({
		ip,
		port: conn.port,
		useTLS: conn.useTLS,
		connected: conn.connected,
		lineTypes: conn.lineTypes,
	}));
}

function closeConnection(ip) {
	const existing = connections.get(ip);
	if (existing) {
		existing.disconnect();
		connections.delete(ip);
		return true;
	}
	return false;
}

function closeAll() {
	for (const ip of [...connections.keys()]) closeConnection(ip);
}

module.exports = {
	openConnection,
	ensureConnection,
	getConnection,
	listConnections,
	closeConnection,
	closeAll,
};
