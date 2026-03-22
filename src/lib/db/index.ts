import { Pool } from "@neondatabase/serverless";
import { drizzle } from "drizzle-orm/neon-serverless";
import * as schema from "./schema";

// Usa Pool (WebSocket) em vez de neon() (HTTP) para suportar transações.
// O driver neon-http é stateless e não consegue manter uma transaction aberta.
const pool = new Pool({ connectionString: process.env.DATABASE_URL! });
export const db = drizzle(pool, { schema });
