// Controller lifecycle: discover units on the LAN, open/close persistent
// connections, and report status.

const express = require('express');
const { asyncHandler, ApiError } = require('../middleware/errors');
const { int } = require('./helpers');
const { discoverControllers } = require('../edidio/discovery');
const { summarize } = require('../edidio/lineTypes');
const mgr = require('../connectionManager');

const router = express.Router();

// GET /api/v1/discover — UDP broadcast probe for controllers on the local network.
router.get(
	'/discover',
	asyncHandler(async (req, res) => {
		const found = await discoverControllers();
		res.json({
			ok: true,
			count: found.length,
			controllers: found.map((c) => ({
				name: c.NAME,
				ip: c.IP,
				mac: c.MAC,
				tls: c.TLS ?? null,
				firmware: c.FW_VER ?? null,
				lines: c.LINES ?? null,
				lineSummary: summarize(c.LINES),
			})),
		});
	}),
);

// GET /api/v1/controllers — list currently pooled connections and their state.
router.get('/controllers', (req, res) => {
	res.json({ ok: true, controllers: mgr.listConnections() });
});

// POST /api/v1/controllers — open (or replace) a persistent connection.
// body: { ip, useTLS?, port? }
router.post(
	'/controllers',
	asyncHandler(async (req, res) => {
		const ip = req.body.ip;
		if (!ip) throw new ApiError(400, 'Missing required field: ip');
		const options = {};
		if (req.body.useTLS !== undefined) {
			options.useTLS = /^(1|true|yes|on)$/i.test(String(req.body.useTLS));
		}
		if (req.body.port !== undefined) {
			options.port = int(req.body.port, 'port', { min: 1, max: 65535 });
		}

		const { conn, connected, error } = await mgr.openConnection(ip, options);
		res.status(connected ? 200 : 202).json({
			ok: true,
			controller: ip,
			connected,
			pending: !connected,
			port: conn.port,
			useTLS: conn.useTLS,
			lineTypes: conn.lineTypes,
			...(error ? { note: error.message } : {}),
		});
	}),
);

// GET /api/v1/controllers/:ip — status of one pooled connection.
router.get('/controllers/:ip', (req, res, next) => {
	const conn = mgr.getConnection(req.params.ip);
	if (!conn) return next(new ApiError(404, `No connection for ${req.params.ip}. POST it first.`));
	res.json({
		ok: true,
		controller: req.params.ip,
		connected: conn.connected,
		port: conn.port,
		useTLS: conn.useTLS,
		lineTypes: conn.lineTypes,
		lineSummary: summarize(conn.lineTypes),
	});
});

// DELETE /api/v1/controllers/:ip — close and stop reconnecting.
router.delete('/controllers/:ip', (req, res, next) => {
	const closed = mgr.closeConnection(req.params.ip);
	if (!closed) return next(new ApiError(404, `No connection for ${req.params.ip}.`));
	res.json({ ok: true, controller: req.params.ip, closed: true });
});

module.exports = router;
