// Stream Deck plugin glue: on key press, build a REST request from the button's
// settings and POST it to the eDIDIO REST API Gateway. The request mapping lives
// in request.js (unit tested); this file is the Stream Deck WebSocket wiring.

let websocket = null

// Called by the Stream Deck app when the plugin starts.
function connectElgatoStreamDeckSocket(inPort, inUUID, inRegisterEvent, inInfo, inActionInfo) {
	websocket = new WebSocket('ws://127.0.0.1:' + inPort)

	websocket.onopen = function () {
		websocket.send(JSON.stringify({ event: inRegisterEvent, uuid: inUUID }))
	}

	websocket.onmessage = function (evt) {
		const json = JSON.parse(evt.data)
		if (json.event === 'keyDown') {
			handleKeyDown(json.context, (json.payload && json.payload.settings) || {})
		}
	}
}

async function handleKeyDown(context, settings) {
	try {
		const req = EdidioRequest.buildRequest(settings)
		const res = await fetch(req.url, { method: req.method, headers: req.headers, body: req.body })
		signal(res.ok ? 'showOk' : 'showAlert', context)
	} catch (err) {
		signal('showAlert', context)
	}
}

function signal(event, context) {
	if (websocket) websocket.send(JSON.stringify({ event: event, context: context }))
}

// Expose for the Stream Deck runtime.
window.connectElgatoStreamDeckSocket = connectElgatoStreamDeckSocket
