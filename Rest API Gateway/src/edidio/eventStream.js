// Live event stream (Event Stream v2, firmware >= 1.4.0) for the JS engine.
//
// The controller pushes events to a client that subscribes with an
// EventStreamMessage (EdidioMessage tag 77). This module:
//   - builds the subscribe / unsubscribe frames,
//   - splits a TCP byte stream into 0xCD frames (skipping keep-alive bytes),
//   - decodes pushed envelopes into the same event objects as the Python engine
//     (edidio_control_py.events), and
//   - turns DALI bus frames into level changes (edidio_control_py.state).
//
// The vendored eDS10_ProtocolBuffer_pb.js predates tag 77, so this uses a small
// protobuf wire reader instead. Fixtures in the tests are produced by the Python
// engine, so both languages decode identical bytes identically.

// --- categories --------------------------------------------------------------

const CATEGORY_BITS = {
	sys: 0, trigger: 1, triggers: 1, inputs: 2, input: 2,
	dali: 3, sensors: 4, sensor: 4, schedule: 5, lists: 6, list: 6,
	config: 7, network: 8, sd: 9, event: 10,
};
const EVENT_BIT = 1 << 10;
const ALL_CATEGORIES_MASK = 0x7ff;

function categoriesToMask(categories) {
	let mask = 0;
	for (const c of categories || []) {
		if (CATEGORY_BITS[c] !== undefined) mask |= 1 << CATEGORY_BITS[c];
	}
	return mask === 0 ? ALL_CATEGORIES_MASK : mask | EVENT_BIT;
}

// --- protobuf wire helpers ---------------------------------------------------

function writeVarint(out, value) {
	let v = value >>> 0;
	while (v > 0x7f) {
		out.push((v & 0x7f) | 0x80);
		v >>>= 7;
	}
	out.push(v);
}

function field(out, num, wireType) {
	writeVarint(out, (num << 3) | wireType);
}

function frame(body) {
	return Uint8Array.from([0xcd, (body.length >> 8) & 0xff, body.length & 0xff, ...body]);
}

function eventStreamFrame(messageId, inner) {
	const body = [];
	field(body, 1, 0);
	writeVarint(body, messageId);
	field(body, 77, 2);
	writeVarint(body, inner.length);
	body.push(...inner);
	return frame(body);
}

function buildSubscribe(categoryMask = ALL_CATEGORIES_MASK, levelThreshold = 2, messageId = 1) {
	const inner = [];
	field(inner, 1, 0); writeVarint(inner, 1);            // subscribe = true
	field(inner, 2, 0); writeVarint(inner, categoryMask);
	field(inner, 3, 0); writeVarint(inner, levelThreshold);
	return eventStreamFrame(messageId, inner);
}

function buildUnsubscribe(messageId = 2) {
	return eventStreamFrame(messageId, []);               // subscribe = false (default)
}

// Parse a protobuf message into { fieldNumber: [values] } (varints as numbers,
// length-delimited fields as Uint8Array). Unknown wire types stop parsing.
function readFields(buf) {
	const fields = {};
	let i = 0;
	const varint = () => {
		let result = 0;
		let shift = 0;
		let byte;
		do {
			if (i >= buf.length) throw new Error('truncated varint');
			byte = buf[i++];
			result += (byte & 0x7f) * 2 ** shift;
			shift += 7;
		} while (byte & 0x80);
		return result;
	};
	while (i < buf.length) {
		const key = varint();
		const num = Math.floor(key / 8);
		const wt = key & 7;
		let value;
		if (wt === 0) value = varint();
		else if (wt === 2) {
			const len = varint();
			value = buf.subarray(i, i + len);
			i += len;
		} else if (wt === 5) { i += 4; continue; }
		else if (wt === 1) { i += 8; continue; }
		else break;
		(fields[num] ||= []).push(value);
	}
	return fields;
}

const u = (f, n) => (f[n] ? f[n][f[n].length - 1] : 0);   // uint32, proto3 default 0
const sub = (f, n) => readFields(f[n] ? f[n][f[n].length - 1] : new Uint8Array());

function triggerInfo(f) {
	return { type: u(f, 1), target: u(f, 2), value: u(f, 3), line_mask: u(f, 4) };
}

// --- DALI frame description --------------------------------------------------

// TX and RX use different frame_type namespaces (mirrors SpektraPlus daliConstants.ts):
//   TX (direction 0): 0=8-bit, 1=16-bit, 2=24-bit; status 0 = SUCCESS, else an outcome
//       code (240 NO_ECHO .. 246 ATTEMPT; older firmware 1-7). A failed send arrives
//       as ATTEMPT then e.g. TIMEOUT per retry — it never reached the lights.
//   RX (direction 1): 3=8-bit, 4=16-bit, 5=24-bit; 2/6/254/255 are receive errors.
const DALI_DIR_TX = 0;
const DALI_DIR_RX = 1;
const TX_STATUS_NAMES = {
	0: 'SUCCESS', 240: 'NO_ECHO', 241: 'BUSY', 242: 'TIMEOUT', 243: 'ERROR',
	244: 'PARTIAL', 245: 'COLLISION', 246: 'ATTEMPT',
	1: 'NO_ECHO', 2: 'BUSY', 3: 'TIMEOUT', 4: 'ERROR', 5: 'PARTIAL', 6: 'COLLISION', 7: 'ATTEMPT',
};
const DALI_CMD_NAMES = { 0: 'OFF', 1: 'FADE_UP', 2: 'FADE_DOWN', 5: 'MAX_LEVEL', 6: 'MIN_LEVEL' };
const DALI_SPECIAL = {
	0xa1: 'TERMINATE', 0xa3: 'DTR0', 0xa5: 'INITIALISE', 0xa7: 'RANDOMISE', 0xa9: 'COMPARE',
	0xab: 'WITHDRAW', 0xad: 'PING', 0xb1: 'SEARCHADDRH', 0xb3: 'SEARCHADDRM', 0xb5: 'SEARCHADDRL',
	0xb7: 'PROGRAM SHORT ADDRESS', 0xb9: 'VERIFY SHORT ADDRESS', 0xbb: 'QUERY SHORT ADDRESS',
	0xc1: 'ENABLE DEVICE TYPE', 0xc3: 'DTR1', 0xc5: 'DTR2',
};

function is16BitFrame(frameType, direction = DALI_DIR_TX) {
	if (direction === DALI_DIR_RX) return frameType === 4;
	return direction === DALI_DIR_TX && frameType === 1;
}

// True if the frame really happened on the bus (TX SUCCESS, or a received frame).
function daliFrameOk(direction, frameType, status) {
	if (direction === DALI_DIR_TX) return status === 0;
	if (direction === DALI_DIR_RX) return frameType >= 3 && frameType <= 5;
	return false;
}

function describeDaliFrame(frameValue, frameType, direction = DALI_DIR_TX) {
	if (!is16BitFrame(frameType, direction)) {
		return `frame 0x${frameValue.toString(16).toUpperCase().padStart(6, '0')}`;
	}
	const addr = (frameValue >> 8) & 0xff;
	const data = frameValue & 0xff;
	const cmd = () => DALI_CMD_NAMES[data] ?? `0x${data.toString(16)}`;
	if (addr === 0xff) return `broadcast ${cmd()}`;
	if (addr === 0xfe) return `broadcast DAPC level ${data}`;
	if (addr >= 0xa0 && addr <= 0xcb) {
		return `${DALI_SPECIAL[addr] ?? `special 0x${addr.toString(16).toUpperCase()}`} ${data}`;
	}
	if ((addr & 0xe0) === 0x80) {
		const group = (addr >> 1) & 0x0f;
		return addr & 1 ? `group ${group} cmd ${cmd()}` : `group ${group} arc ${data}`;
	}
	const a = (addr >> 1) & 0x3f;
	return addr & 1 ? `addr ${a} cmd ${cmd()}` : `addr ${a} arc ${data}`;
}

// --- decode ------------------------------------------------------------------

// Decode one frame body (header stripped). Returns an event object, or null for
// the subscribe ACK / anything that isn't an event-stream push.
function decodeFrame(body) {
	let top;
	try {
		top = readFields(body);
	} catch {
		return null;
	}
	if (!top[77]) return null;
	const es = readFields(top[77][top[77].length - 1]);
	if (u(es, 4)) return null;                              // ack
	const ev = { seq: u(es, 5), category: u(es, 8), level: u(es, 9), at: new Date().toISOString() };
	if (es[18]) {
		const d = sub(es, 18);
		const frameValue = u(d, 5);
		const [direction, frameType, status] = [u(d, 2), u(d, 3), u(d, 4)];
		Object.assign(ev, {
			kind: 'dali', line: u(d, 1), direction, frame_type: frameType,
			status, frame: frameValue, ok: daliFrameOk(direction, frameType, status),
			decoded: describeDaliFrame(frameValue, frameType, direction),
		});
		if (direction === DALI_DIR_TX) ev.status_name = TX_STATUS_NAMES[status] ?? `STATUS_${status}`;
	} else if (es[11]) {
		const i = sub(es, 11);
		Object.assign(ev, {
			kind: 'input', index: u(i, 1), source: u(i, 2), press: u(i, 3),
			action: triggerInfo(sub(i, 4)), dali_line: u(i, 5), dali_address: u(i, 6),
		});
	} else if (es[12]) {
		const s = sub(es, 12);
		Object.assign(ev, {
			kind: 'sensor', index: u(s, 1), motion: u(s, 4), light: u(s, 3),
			lux: u(s, 5), dali_line: u(s, 6), dali_address: u(s, 7),
		});
	} else if (es[20]) {
		const s = sub(es, 20);
		Object.assign(ev, { kind: 'spektra', zone: u(s, 1), action: u(s, 2), target: u(s, 3), index: u(s, 4) });
	} else if (es[21]) {
		const c = sub(es, 21);
		Object.assign(ev, { kind: 'command', source: u(c, 1), action: triggerInfo(sub(c, 2)), zone: u(c, 3) });
	} else if (es[17]) {
		Object.assign(ev, { kind: 'net', event: u(sub(es, 17), 1) });
	} else if (es[10]) {
		Object.assign(ev, { kind: 'text', text: Buffer.from(es[10][0]).toString('utf8') });
	} else {
		const other = { 13: 'list', 14: 'schedule', 15: 'config', 16: 'boot', 19: 'raw' };
		const num = Object.keys(other).find((n) => es[n]);
		ev.kind = num ? other[num] : 'unknown';
	}
	return ev;
}

// --- state -------------------------------------------------------------------

const DALI_ARC_LEVEL_MAX = 254;
const DALI_GROUP_ADDRESS_BASE = 64;
const DALI_BROADCAST_ADDRESS = 80;

function edidioAddress(addrByte) {
	if ((addrByte & 0x80) === 0) return (addrByte >> 1) & 0x3f;
	if ((addrByte & 0xe0) === 0x80) return DALI_GROUP_ADDRESS_BASE + ((addrByte >> 1) & 0x0f);
	if (addrByte >= 0xfc) return DALI_BROADCAST_ADDRESS;
	return null;
}

function targetOf(address) {
	if (address === DALI_BROADCAST_ADDRESS) return 'broadcast';
	return address >= DALI_GROUP_ADDRESS_BASE ? 'group' : 'address';
}

// Decode a `kind: 'dali'` event into a level change, or null if the frame doesn't
// change light output. Lines are 1-based; addresses use the eDIDIO convention
// (0-63 short, 64+g group, 80 broadcast). `level` is null when it depends on
// device config (RECALL MIN, GO TO SCENE).
function daliChange(ev) {
	if (!ev || ev.kind !== 'dali' || ev.line === 0xff) return null;
	const direction = ev.direction ?? DALI_DIR_TX;
	if (!is16BitFrame(ev.frame_type, direction)) return null;
	if (!daliFrameOk(direction, ev.frame_type, ev.status ?? 0)) return null; // failed TX / RX error
	const addrByte = (ev.frame >> 8) & 0xff;
	const data = ev.frame & 0xff;
	const address = edidioAddress(addrByte);
	if (address === null) return null;
	const base = { line: ev.line + 1, address, target: targetOf(address), scene: null };
	if ((addrByte & 1) === 0) {
		if (data === 0xff) return null;                    // DAPC MASK: no change
		return { ...base, level: Math.min(data, DALI_ARC_LEVEL_MAX), command: 'arc' };
	}
	if (data === 0x00) return { ...base, level: 0, command: 'off' };
	if (data === 0x05) return { ...base, level: DALI_ARC_LEVEL_MAX, command: 'recall_max' };
	if (data === 0x06) return { ...base, level: null, command: 'recall_min' };
	if (data >= 0x10 && data < 0x20) return { ...base, level: null, scene: data - 0x10, command: 'scene' };
	return null;
}

// Folds level changes into a `line:address -> level` table. Broadcast updates
// every known target on the line; pass `groups` ({ 'line:group': [addresses] })
// to have group frames update member addresses too.
// The controller reports each of its own transmissions twice (TX SUCCESS + the RX
// echo it hears on the bus — verified on fw 1.6.2), so an identical change repeated
// within `dedupeMs` is dropped: apply() returns [] instead of publishing it twice.
class LevelTracker {
	constructor(groups = {}, { dedupeMs = 300, now = Date.now } = {}) {
		this.levels = new Map();
		this.groups = groups;
		this.dedupeMs = dedupeMs;
		this.now = now;
		this.last = null;
	}

	apply(change) {
		const t = this.now();
		const key = `${change.line}:${change.address}:${change.level}:${change.scene ?? ''}:${change.command ?? ''}`;
		if (this.last && this.last.key === key && t - this.last.t <= this.dedupeMs) return [];
		this.last = { key, t };
		const targets = [change.address];
		if (change.target === 'group') {
			targets.push(...(this.groups[`${change.line}:${change.address - DALI_GROUP_ADDRESS_BASE}`] || []));
		} else if (change.target === 'broadcast') {
			for (const key of this.levels.keys()) {
				const [line, addr] = key.split(':').map(Number);
				if (line === change.line) targets.push(addr);
			}
		}
		const touched = [];
		for (const a of new Set(targets)) {
			this.levels.set(`${change.line}:${a}`, change.level);
			touched.push({ line: change.line, address: a, level: change.level });
		}
		return touched;
	}

	snapshot() {
		return Object.fromEntries(this.levels);
	}
}

// --- framing -----------------------------------------------------------------

// Splits a TCP byte stream into 0xCD-framed bodies, resynchronising on 0xCD and
// skipping unframed bytes (e.g. 0xFF 0xF6 keep-alives). push() returns bodies.
class FrameReader {
	constructor() {
		this.buf = Buffer.alloc(0);
	}

	push(chunk) {
		this.buf = Buffer.concat([this.buf, Buffer.from(chunk)]);
		const out = [];
		for (;;) {
			const start = this.buf.indexOf(0xcd);
			if (start < 0) {
				this.buf = Buffer.alloc(0);
				break;
			}
			if (start > 0) this.buf = this.buf.subarray(start);
			if (this.buf.length < 3) break;
			const len = (this.buf[1] << 8) | this.buf[2];
			if (len === 0) {
				this.buf = this.buf.subarray(1);
				continue;
			}
			if (this.buf.length < 3 + len) break;
			out.push(Uint8Array.from(this.buf.subarray(3, 3 + len)));
			this.buf = this.buf.subarray(3 + len);
		}
		return out;
	}
}

module.exports = {
	ALL_CATEGORIES_MASK,
	CATEGORY_BITS,
	categoriesToMask,
	buildSubscribe,
	buildUnsubscribe,
	describeDaliFrame,
	decodeFrame,
	daliChange,
	LevelTracker,
	FrameReader,
};
