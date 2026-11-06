import html from '../lib/library.html?raw';
export const dynamic = 'force-dynamic';
export function GET() {
  return new Response(html, { headers: {
    'Content-Type':'text/html; charset=utf-8', 'Cache-Control':'private, no-store',
    'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer',
    'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
  }});
}
