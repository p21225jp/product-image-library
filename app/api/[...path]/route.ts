import { env } from 'cloudflare:workers';
import { handleLibrary } from '../../../lib/library';
export const dynamic = 'force-dynamic';
export const GET = (request:Request)=>handleLibrary(request, env as any);
export const POST = GET;
export const PUT = GET;
export const DELETE = GET;
