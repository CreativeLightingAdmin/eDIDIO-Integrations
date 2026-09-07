// Error plumbing: a typed HTTP error, an async wrapper so route handlers can
// throw, and the terminal Express error handler that renders JSON.

class ApiError extends Error {
	constructor(status, message, details) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		if (details !== undefined) this.details = details;
	}
}

// Wrap an async route handler so rejected promises reach Express' error chain.
function asyncHandler(fn) {
	return (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);
}

// eslint-disable-next-line no-unused-vars -- Express identifies error handlers by arity (4 args).
function errorHandler(err, req, res, next) {
	const status = err.status || 500;
	if (status >= 500) console.error('[gateway]', err);
	res.status(status).json({
		ok: false,
		error: err.message || 'Internal Server Error',
		...(err.details !== undefined ? { details: err.details } : {}),
	});
}

module.exports = { ApiError, asyncHandler, errorHandler };
