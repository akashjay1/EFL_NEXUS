import { parse } from 'pgsql-parser';
import { readFile } from 'node:fs/promises';

const migration = await readFile(new URL('../supabase/001_operator_presence.sql', import.meta.url), 'utf8');
const ast = await parse(migration);
console.log(`PostgreSQL parser accepted ${ast.stmts.length} statements.`);
console.log('This checks outer SQL syntax. Live Supabase execution and authorization checks are still required.');
