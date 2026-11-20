const FALLBACK_ERROR_CODE = "UNEXPECTED_RESPONSE";
const FALLBACK_MESSAGE = "The request could not be completed.";
const NETWORK_ERROR_CODE = "ORCHESTRATOR_UNREACHABLE";
const NETWORK_MESSAGE = "The local orchestrator could not be reached. Check that it is running.";
const TIMEOUT_ERROR_CODE = "REQUEST_TIMED_OUT";
const TIMEOUT_MESSAGE = "The local orchestrator took too long to respond.";

/**
 * A failed API call in the contract's error shape. `message` is always safe to
 * show to the user; `traceId` is empty when the failure never reached the server.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly traceId: string;
  readonly status: number;

  constructor(code: string, message: string, traceId: string, status: number, cause?: unknown) {
    super(message, { cause });
    this.name = "ApiError";
    this.code = code;
    this.traceId = traceId;
    this.status = status;
  }
}

const isRecord = (candidate: unknown): candidate is Record<string, unknown> =>
  typeof candidate === "object" && candidate !== null && !Array.isArray(candidate);

/**
 * Builds an ApiError from a non-2xx response. A body that is not in the contract
 * shape yields a generic message rather than leaking whatever the server sent.
 *
 * @param response - The failed fetch response
 * @returns An ApiError carrying the server's message and trace ID where present
 */
export async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // A non-JSON error body is expected from proxies; the fallback below covers it.
    body = null;
  }
  if (isRecord(body) && typeof body.message === "string") {
    const code = typeof body.error === "string" ? body.error : FALLBACK_ERROR_CODE;
    const traceId = typeof body.trace_id === "string" ? body.trace_id : "";
    return new ApiError(code, body.message, traceId, response.status);
  }
  return new ApiError(FALLBACK_ERROR_CODE, FALLBACK_MESSAGE, "", response.status);
}

/**
 * Translates a thrown fetch failure into an ApiError with user-safe wording.
 * The original exception is kept as `cause` and never shown.
 *
 * @param cause - Whatever fetch rejected with
 * @returns An ApiError describing a timeout or an unreachable orchestrator
 */
export function toNetworkError(cause: unknown): ApiError {
  const isTimeout = cause instanceof DOMException && cause.name === "TimeoutError";
  if (isTimeout) {
    return new ApiError(TIMEOUT_ERROR_CODE, TIMEOUT_MESSAGE, "", 0, cause);
  }
  return new ApiError(NETWORK_ERROR_CODE, NETWORK_MESSAGE, "", 0, cause);
}

/**
 * Normalises any thrown value into an ApiError so the UI only ever renders
 * contract-shaped, user-safe messages.
 *
 * @param thrown - A caught value of unknown type
 * @returns The same ApiError if it already is one, otherwise a generic one
 */
export function asApiError(thrown: unknown): ApiError {
  if (thrown instanceof ApiError) {
    return thrown;
  }
  return new ApiError(FALLBACK_ERROR_CODE, FALLBACK_MESSAGE, "", 0, thrown);
}
