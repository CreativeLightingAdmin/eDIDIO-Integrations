// Line-type awareness for eDIDIO controllers.
//
// A controller has up to 4 physical "lines" (daughter-board slots), and each can
// be a different type. The controller reports them in its UDP discovery JSON as a
// `LINES` array of LineType numbers, e.g. [1,2,2,2] = Line 1 DALI, Lines 2-4 DMX.
//
// DALI and DMX are driven by different protobuf messages, so a command must target
// a line of the matching type. This module is the single source of truth for
// mapping line numbers to masks and validating a line against an expected protocol.

const messages = require('./eDS10_ProtocolBuffer_pb.js');

// Re-export the generated enum so values never drift from the protocol. Note the
// bundled protobuf only defines 0-3; LINE_AUTO (4) is handled numerically below.
const LineType = messages.LineType; // { LINE_EMPTY:0, LINE_DALI:1, LINE_DMX:2, LINE_DMX_IN:3 }
const LINE_AUTO = 4;

const LINE_LABELS = {
	0: 'Empty',
	1: 'DALI',
	2: 'DMX',
	3: 'DMX-In',
	4: 'Auto',
};

// 1-based line number (1-4) -> single-bit mask (0b0001 .. 0b1000).
function maskForLine(line) {
	return 1 << (line - 1);
}

// Human label for a given line, or 'Unknown' when the type map isn't available.
function labelForLine(lineTypes, line) {
	if (!Array.isArray(lineTypes)) return 'Unknown';
	const type = lineTypes[line - 1];
	if (type === undefined) return 'Unknown';
	return LINE_LABELS[type] ?? `Type ${type}`;
}

// Validate that `line` is the right type for an `expected` protocol ('DALI'|'DMX').
// Returns { ok: true } to proceed, or { ok: false, reason } to block.
// When lineTypes is unknown (discovery didn't populate it), validation is skipped.
function validateLine(lineTypes, line, expected) {
	if (!Array.isArray(lineTypes)) return { ok: true }; // unknown -> don't block

	const type = lineTypes[line - 1];
	if (type === undefined) return { ok: true }; // out of range -> unknown

	if (type === LineType.LINE_EMPTY) {
		return { ok: false, reason: `Line ${line} is empty / not populated.` };
	}
	if (type === LINE_AUTO) return { ok: true }; // AUTO accepts either technology

	if (expected === 'DALI') {
		if (type === LineType.LINE_DMX || type === LineType.LINE_DMX_IN) {
			return { ok: false, reason: `Line ${line} is a DMX line — use \`/light color\`.` };
		}
	} else if (expected === 'DMX') {
		if (type === LineType.LINE_DMX_IN) {
			return { ok: false, reason: `Line ${line} is a DMX **input** line, not an output.` };
		}
		if (type === LineType.LINE_DALI) {
			return { ok: false, reason: `Line ${line} is a DALI line — use \`/light on|off|level\`.` };
		}
	}
	return { ok: true };
}

// Compact summary like "Line 1: DALI · Lines 2-4: DMX". 'Unknown' when unavailable.
function summarize(lineTypes) {
	if (!Array.isArray(lineTypes) || lineTypes.length === 0) return 'Unknown';

	const parts = [];
	let start = 0;
	for (let i = 1; i <= lineTypes.length; i++) {
		if (i === lineTypes.length || lineTypes[i] !== lineTypes[start]) {
			const label = LINE_LABELS[lineTypes[start]] ?? `Type ${lineTypes[start]}`;
			if (start === i - 1) {
				parts.push(`Line ${start + 1}: ${label}`);
			} else {
				parts.push(`Lines ${start + 1}-${i}: ${label}`);
			}
			start = i;
		}
	}
	return parts.join(' · ');
}

module.exports = { LineType, LINE_AUTO, LINE_LABELS, maskForLine, labelForLine, validateLine, summarize };
