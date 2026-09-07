// Discover eDIDIO controllers on the local network via UDP broadcast.
//
// Protocol (matches the SpektraPlus desktop app):
//   - Send the probe string "D" to UDP port 30303.
//   - Send it to the DIRECTED SUBNET BROADCAST address of every active network
//     interface (IP | ~netmask), NOT the global 255.255.255.255 — many networks
//     don't route the global broadcast, so the directed one is what reaches the
//     controller.
//   - Controllers reply with either JSON {NAME,MAC,IP,TLS,FW_VER,LINES} or a
//     legacy "NAME\r\nMAC" text payload. We ignore our own "D" echo.
//   - Newer firmware includes `TLS: true`, meaning the unit accepts a TLS
//     connection on port 443 (older units are plain TCP on port 23).

const dgram = require('node:dgram');
const os = require('node:os');

const DISCOVERY_PORT = 30303;
const PROBE = Buffer.from('D', 'utf8');

// VPN heuristic (mirrors SpektraPlus): on a 172.x interface, also unicast to a
// small range of likely controller addresses since broadcast may not traverse.
const VPN_PREFIX = '172.';
const VPN_UNICAST_START = 8;
const VPN_UNICAST_END = 13;

// Build the list of target IPs to probe: the directed broadcast for every
// active IPv4 interface, plus VPN unicast targets where applicable.
function getDiscoveryTargets() {
	const targets = new Set();
	const interfaces = os.networkInterfaces();

	for (const name of Object.keys(interfaces)) {
		for (const iface of interfaces[name] || []) {
			if (iface.family !== 'IPv4' || iface.internal) continue;

			const ip = iface.address.split('.').map(Number);
			const mask = iface.netmask.split('.').map(Number);
			// Broadcast address = IP OR (NOT netmask)
			const broadcast = ip.map((part, i) => part | (~mask[i] & 255)).join('.');
			targets.add(broadcast);

			if (iface.address.startsWith(VPN_PREFIX)) {
				const base = `${ip[0]}.${ip[1]}.${ip[2]}`;
				for (let i = VPN_UNICAST_START; i <= VPN_UNICAST_END; i++) {
					const target = `${base}.${i}`;
					if (target !== iface.address) targets.add(target);
				}
			}
		}
	}

	// Fallback if no interfaces were enumerable.
	if (targets.size === 0) targets.add('255.255.255.255');
	return [...targets];
}

// Parse a single UDP response payload into a controller info object, or null.
function parseResponse(text, ip) {
	if (text === 'D') return null; // our own echo

	if (text.startsWith('{') && text.endsWith('}')) {
		try {
			const json = JSON.parse(text);
			return { ...json, IP: ip };
		} catch {
			return null;
		}
	}

	// Legacy format: "NAME\r\nMAC"
	const parts = text.split('\r\n');
	if (parts.length >= 2) {
		return { NAME: parts[0], MAC: parts[1], IP: ip };
	}
	return null;
}

// Returns a Promise resolving to an array of controller info objects:
//   { NAME, MAC, IP, TLS?, FW_VER?, LINES? }
function discoverControllers(timeoutMs = 2000) {
	return new Promise((resolve) => {
		const socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });
		const found = new Map(); // ip -> info
		let done = false;

		const finish = () => {
			if (done) return;
			done = true;
			try {
				socket.close();
			} catch {
				/* already closed */
			}
			resolve([...found.values()]);
		};

		socket.on('error', finish);

		socket.on('message', (msg, rinfo) => {
			const info = parseResponse(msg.toString('utf8').trim(), rinfo.address);
			if (info && !found.has(rinfo.address)) found.set(rinfo.address, info);
		});

		socket.on('listening', () => {
			socket.setBroadcast(true);
			for (const target of getDiscoveryTargets()) {
				socket.send(PROBE, DISCOVERY_PORT, target, (err) => {
					// A single unreachable target shouldn't abort discovery.
					if (err) console.warn(`[discovery] send to ${target} failed: ${err.message}`);
				});
			}
			setTimeout(finish, timeoutMs);
		});

		// Bind to the discovery port on all interfaces so controllers that reply
		// to the source port reach us.
		socket.bind(DISCOVERY_PORT, '0.0.0.0');
	});
}

module.exports = { discoverControllers, DISCOVERY_PORT };
