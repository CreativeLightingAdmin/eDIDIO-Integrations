#!/usr/bin/env node
// Raycast Script Command: a general eDIDIO command dispatcher.
//
// @raycast.schemaVersion 1
// @raycast.title eDIDIO
// @raycast.mode compact
// @raycast.packageName eDIDIO
// @raycast.icon 💡
// @raycast.argument1 { "type": "text", "placeholder": "scene 3 | level 5 200 | color #FF0000 | on 5 | seq 0" }
//
// Also works as an Alfred Script Filter / Workflow "Run Script" action:
//   node commands/edidio.js "scene 3"

const { run } = require('../lib/edidio')

const argv = (process.argv[2] || '').trim().split(/\s+/).filter(Boolean)

run(argv, process)
	.then(() => console.log(`OK: ${argv.join(' ')}`))
	.catch((err) => {
		console.error(String(err.message || err))
		process.exit(1)
	})
