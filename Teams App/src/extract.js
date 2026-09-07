// Extract the eDIDIO command text from a Teams Outgoing Webhook payload.
//
// Teams sends the message as an Activity: { type, text, ... }. When users
// @-mention the webhook the `text` includes the mention markup, e.g.
//   "<at>eDIDIO</at> scene 3"  or  "eDIDIO scene 3".
// We strip any leading <at>…</at> / HTML tags and an optional bot-name word so
// the mapper receives just "scene 3".

function extractCommand(activity, botName) {
	let text = (activity && activity.text) || ''
	// Remove HTML tags (e.g. <at>eDIDIO</at>).
	text = text.replace(/<[^>]*>/g, ' ')
	// Collapse whitespace.
	text = text.replace(/\s+/g, ' ').trim()
	// Strip a leading bot-name mention word if present (with args after it, or
	// on its own when the message is just the mention).
	if (botName) {
		const re = new RegExp('^' + botName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\s+|$)', 'i')
		text = text.replace(re, '')
	}
	return text.trim()
}

module.exports = { extractCommand }
