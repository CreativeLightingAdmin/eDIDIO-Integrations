// eDIDIO Twitch bot entry point.
//
// Connects to Twitch chat (tmi.js) and to the eDIDIO controller, and routes:
//   - chat commands (!scene, !light, !color, …)
//   - bit cheers (via the chat 'cheer' event)
//   - channel-point redemptions (see the README note on EventSub)
// through the pure mapper into eDIDIO frames.

const tmi = require('tmi.js')
const { config, assertConfigured } = require('./src/config')
const { ControllerConnection } = require('./src/edidio/connection')
const { handleChat, handleReward, handleBits } = require('./src/mapper')

async function main() {
	assertConfigured()

	// eDIDIO connection (auto-reconnect + keep-alive).
	const conn = new ControllerConnection(config.edidioHost, {
		port: config.edidioPort,
		useTLS: config.edidioUseTLS,
	})
	conn.on('connect', () => console.log(`[edidio] connected to ${config.edidioHost}`))
	conn.on('disconnect', () => console.warn('[edidio] disconnected; retrying'))
	conn.connect().catch(() => {})

	// Twitch chat.
	const client = new tmi.Client({
		options: { debug: false },
		identity: { username: config.username, password: config.oauth },
		channels: [config.channel],
	})

	async function fire(result, replyCtx) {
		if (!result) return
		if (result.error) {
			if (config.announce && replyCtx) client.say(config.channel, `@${replyCtx} ${result.error}`)
			return
		}
		const sent = await conn.send(result.frame).catch(() => false)
		const msg = sent ? `💡 ${result.label}` : '⚠️ controller not connected'
		console.log(`[edidio] ${msg}`)
		if (config.announce && replyCtx) client.say(config.channel, `@${replyCtx} ${msg}`)
	}

	client.on('message', (channel, tags, message, self) => {
		if (self) return
		// Bit cheers arrive as messages with a bits count.
		if (tags.bits) {
			fire(handleBits(config.commands, Number(tags.bits)), tags.username)
		}
		fire(handleChat(config.commands, message.trim(), tags), tags.username)
	})

	// Channel-point redemptions: tmi.js chat doesn't deliver these. If you bridge
	// them in (EventSub / PubSub), call this with the reward title:
	//   fire(handleReward(config.commands, rewardTitle), redeemer)
	client.handleRewardRedemption = (rewardTitle, redeemer) =>
		fire(handleReward(config.commands, rewardTitle), redeemer)

	client.on('connected', () => console.log(`[twitch] connected to #${config.channel}`))
	await client.connect()
}

main().catch((err) => {
	console.error(err.message || err)
	process.exit(1)
})
