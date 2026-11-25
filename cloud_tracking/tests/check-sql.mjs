import { createRequire } from 'node:module';
const { parse }=createRequire(new URL('../dashboard/package.json',import.meta.url))('pgsql-parser');
import { readFile,readdir } from 'node:fs/promises';
const root=new URL('../supabase/migrations/',import.meta.url);
for (const name of (await readdir(root)).filter(n=>n.endsWith('.sql'))) {
  const ast=await parse(await readFile(new URL(name,root),'utf8'));
  console.log(`${name}: ${ast.stmts.length} outer SQL statements parsed. PL/pgSQL requires live database verification.`);
}
