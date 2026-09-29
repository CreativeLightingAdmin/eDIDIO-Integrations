// Event stream decoder tests. Every fixture below was produced by the Python
// engine (edidio_control_py.events / _v2 protobuf), so these assert byte-level
// parity between the two engines.

const test = require('node:test');
const assert = require('node:assert/strict');
const es = require('../eventStream');

const hex = (s) => Uint8Array.from(Buffer.from(s, 'hex'));
const FIX = {
	subscribe: 'cd000c0801ea04070801108c081802', // dali + inputs, threshold 2, id 1
	unsubscribe: 'cd00050802ea0400',
	ack: 'ea04022001',
	dali: 'ea040e280540039201070801180128c815', // line 1, 16-bit, 0x0AC8
	input: 'ea04152806400a5a0f0803180122090807100218fe012001',
	sensor: 'ea040c2807400a6206080220032878',
	spektra: 'ea040f2808400aa201080801100118012004',
	text: 'ea040d280948025207626f6f74206f6b',
	bigseq: 'ea040f28e0a712400392010618042885fe03', // seq 300000, frame_type 4, 0xFF05
};

test('subscribe/unsubscribe frames match the Python engine', () => {
	const mask = es.categoriesToMask(['dali', 'inputs']);
	assert.equal(Buffer.from(es.buildSubscribe(mask, 2, 1)).toString('hex'), FIX.subscribe);
	assert.equal(Buffer.from(es.buildUnsubscribe()).toString('hex'), FIX.unsubscribe);
	assert.equal(es.categoriesToMask([]), es.ALL_CATEGORIES_MASK);
});

test('decodes each entry type', () => {
	assert.equal(es.decodeFrame(hex(FIX.ack)), null);
	const d = es.decodeFrame(hex(FIX.dali));
	assert.deepEqual(
		[d.kind, d.seq, d.line, d.frame_type, d.frame, d.decoded],
		['dali', 5, 1, 1, 0x0ac8, 'addr 5 arc 200'],
	);
	const i = es.decodeFrame(hex(FIX.input));
	assert.equal(i.kind, 'input');
	assert.equal(i.index, 3);
	assert.deepEqual(i.action, { type: 7, target: 2, value: 254, line_mask: 1 });
	const s = es.decodeFrame(hex(FIX.sensor));
	assert.deepEqual([s.kind, s.index, s.motion, s.lux], ['sensor', 2, 3, 120]);
	const sp = es.decodeFrame(hex(FIX.spektra));
	assert.deepEqual([sp.kind, sp.zone, sp.action, sp.target, sp.index], ['spektra', 1, 1, 1, 4]);
	assert.equal(es.decodeFrame(hex(FIX.text)).text, 'boot ok');
	const b = es.decodeFrame(hex(FIX.bigseq));
	assert.equal(b.seq, 300000);
	assert.equal(b.decoded, 'frame 0x00FF05'); // TX (direction 0) type 4 isn't a 16-bit frame
	assert.equal(es.decodeFrame(hex('0801')), null); // not an event-stream push
});

// Real sequence from a controller on fw 1.6.2 for "addr 0 arc 200" (bytes rebuilt
// from the captured field values): TX ATTEMPT, TX SUCCESS, then the RX echo.
const LIVE = {
	attempt: 'ea040f280a4003920108180120f60128c801',
	success: 'ea040c280a4003920105180128c801',
	rxEcho: 'ea0410280a400392010910011804201028c801',
	rxPartial: 'ea040b280b400392010410011806',
};

test('live fw 1.6.2 sequence: only real frames count, echo is deduplicated', () => {
	const [attempt, success, echo, partial] =
		[LIVE.attempt, LIVE.success, LIVE.rxEcho, LIVE.rxPartial].map((h) => es.decodeFrame(hex(h)));
	assert.deepEqual([attempt.ok, attempt.status_name], [false, 'ATTEMPT']);
	assert.deepEqual([success.ok, success.status_name], [true, 'SUCCESS']);
	assert.deepEqual([echo.ok, echo.direction, echo.frame_type, echo.decoded], [true, 1, 4, 'addr 0 arc 200']);
	assert.equal(es.daliChange(attempt), null);
	assert.equal(es.daliChange(partial), null);
	assert.equal(es.daliChange({ ...success, status: 242 }), null); // TIMEOUT (no bus power)

	let clock = 1000;
	const t = new es.LevelTracker({}, { now: () => clock });
	assert.deepEqual(t.apply(es.daliChange(success)), [{ line: 1, address: 0, level: 200 }]);
	clock += 20;
	assert.deepEqual(t.apply(es.daliChange(echo)), []); // echo of our own TX
	clock += 1000;
	assert.equal(t.apply(es.daliChange(echo)).length, 1); // a later identical frame counts again
	assert.equal(es.describeDaliFrame(0xad00, 1), 'PING 0');
});

test('daliChange mirrors edidio_control_py.state', () => {
	const ev = (frame, frame_type = 1, line = 0, direction = 0) => ({ kind: 'dali', frame, frame_type, line, direction });
	assert.deepEqual(es.daliChange(ev(0x0ac8, 1, 1)),
		{ line: 2, address: 5, target: 'address', scene: null, level: 200, command: 'arc' });
	assert.equal(es.daliChange(ev(0x8680)).address, 67);
	assert.equal(es.daliChange(ev(0xff00)).level, 0);
	assert.equal(es.daliChange(ev(0xff05, 4, 0, 1)).level, 254); // RX 16-bit
	assert.equal(es.daliChange(ev(0xff05, 4)), null); // TX type 4 isn't 16-bit
	assert.equal(es.daliChange(ev(0x0b13)).scene, 3);
	assert.equal(es.daliChange(ev(0x0aff)), null);
	assert.equal(es.daliChange(ev(0x0b90)), null);
	assert.equal(es.daliChange(ev(0x45, 0)), null);
});

test('LevelTracker applies group members and broadcast', () => {
	const t = new es.LevelTracker({ '1:3': [5, 6] });
	const touched = t.apply({ line: 1, address: 67, target: 'group', level: 100 });
	assert.deepEqual(touched.map((x) => x.address), [67, 5, 6]);
	t.apply({ line: 1, address: 80, target: 'broadcast', level: 0 });
	assert.equal(t.snapshot()['1:5'], 0);
	assert.equal(t.snapshot()['1:67'], 0);
});

test('FrameReader splits, skips keep-alives and handles partial chunks', () => {
	const r = new es.FrameReader();
	const body = hex(FIX.dali);
	const framed = Buffer.concat([Buffer.from([0xff, 0xf6, 0xcd, 0, body.length]), Buffer.from(body)]);
	assert.deepEqual(r.push(framed.subarray(0, 6)), []);
	const out = r.push(Buffer.concat([framed.subarray(6), Buffer.from([0xff, 0xf6])]));
	assert.equal(out.length, 1);
	assert.equal(es.decodeFrame(out[0]).frame, 0x0ac8);
});
