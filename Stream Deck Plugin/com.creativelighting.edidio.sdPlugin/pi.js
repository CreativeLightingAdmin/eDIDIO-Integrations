// Property Inspector: load/save the button's settings and show only the fields
// relevant to the selected command.

let websocket = null
let uuid = null
let settings = {}

const FIELDS = ['gatewayUrl', 'apiKey', 'controller', 'command', 'line', 'address', 'group', 'scene', 'level', 'hex', 'zone', 'type', 'index', 'action']

// Which field rows show for each command.
const VISIBLE = {
	scene: ['line', 'scene', 'group'],
	level: ['line', 'address', 'level'],
	group_level: ['line', 'group', 'level'],
	on: ['line', 'address'],
	off: ['line', 'address'],
	dmx_color: ['line', 'hex'],
	spektra: ['zone', 'type', 'index', 'action'],
}

function connectElgatoStreamDeckSocket(inPort, inUUID, inRegisterEvent, inInfo, inActionInfo) {
	uuid = inUUID
	try {
		const info = JSON.parse(inActionInfo)
		settings = (info.payload && info.payload.settings) || {}
	} catch (e) {
		settings = {}
	}
	websocket = new WebSocket('ws://127.0.0.1:' + inPort)
	websocket.onopen = function () {
		websocket.send(JSON.stringify({ event: inRegisterEvent, uuid: inUUID }))
		populate()
	}
	websocket.onmessage = function (evt) {
		const json = JSON.parse(evt.data)
		if (json.event === 'didReceiveSettings') {
			settings = (json.payload && json.payload.settings) || {}
			populate()
		}
	}
}

function populate() {
	FIELDS.forEach(function (id) {
		const el = document.getElementById(id)
		if (el && settings[id] !== undefined) el.value = settings[id]
	})
	toggleFields()
}

function collect() {
	FIELDS.forEach(function (id) {
		const el = document.getElementById(id)
		if (el) settings[id] = el.value
	})
}

function save() {
	collect()
	if (websocket) {
		websocket.send(JSON.stringify({ event: 'setSettings', context: uuid, payload: settings }))
	}
	toggleFields()
}

function toggleFields() {
	const cmd = (document.getElementById('command') || {}).value || 'scene'
	const show = VISIBLE[cmd] || []
	;['line', 'address', 'group', 'scene', 'level', 'hex', 'zone', 'type', 'index', 'action'].forEach(function (f) {
		const row = document.querySelector('.f-' + f)
		if (row) row.classList.toggle('hidden', show.indexOf(f) === -1)
	})
}

window.addEventListener('DOMContentLoaded', function () {
	FIELDS.forEach(function (id) {
		const el = document.getElementById(id)
		if (el) el.addEventListener('change', save)
	})
})

window.connectElgatoStreamDeckSocket = connectElgatoStreamDeckSocket
