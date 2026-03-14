export class ApiRequestError extends Error {
  status: number;
  payload: any;

  constructor(message: string, status: number, payload: any = null) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.payload = payload;
  }
}

export function getApiErrorStatus(error: unknown): number | null {
  return typeof (error as any)?.status === "number" ? (error as any).status : null;
}

export function isApiErrorStatus(error: unknown, status: number): boolean {
  return getApiErrorStatus(error) === status;
}

export async function parseApiResponse(resp: Response) {
  if (resp.ok) return resp.json();

  let payload: any = null;
  try {
    payload = await resp.json();
  } catch {
    payload = null;
  }

  const detail = payload?.detail;
  const error = payload?.error;
  const errorId = payload?.error_id;

  let message = "Request failed";
  if (typeof detail === "string" && detail) {
    message = detail;
  } else if (Array.isArray(detail) && detail.length) {
    message = detail.map((item) => item?.msg || JSON.stringify(item)).join(", ");
  } else if (typeof error === "string" && error) {
    message = errorId ? `${error} (${errorId})` : error;
  } else {
    const text = await resp.text().catch(() => "");
    if (text) message = text;
  }

  throw new ApiRequestError(message, resp.status, payload);
}
