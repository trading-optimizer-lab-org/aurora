export interface AuthResult {
  ok: boolean;
  suffix?: string;
}

export function authorizePath(pathname: string, secret: string): AuthResult {
  if (!secret || !pathname.startsWith("/s/")) return { ok: false };
  const parts = pathname.split("/");
  if (parts.length < 3 || parts[2] !== secret) return { ok: false };
  const suffix = `/${parts.slice(3).join("/")}`.replace(/\/+/g, "/");
  return { ok: true, suffix: suffix === "/" ? "/" : suffix };
}

export function authorizeSync(request: Request, token: string | undefined): boolean {
  if (!token) return false;
  const supplied = request.headers.get("Authorization") || "";
  const expected = `Bearer ${token}`;
  if (supplied.length !== expected.length) return false;
  let diff = 0;
  for (let index = 0; index < expected.length; index += 1) {
    diff |= supplied.charCodeAt(index) ^ expected.charCodeAt(index);
  }
  return diff === 0;
}
