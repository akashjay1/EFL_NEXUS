import { build } from 'esbuild';
import { mkdir, readFile, copyFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(await readFile(path.join(root, 'public-config.json'), 'utf8'));
if (!/^https:\/\/[a-z0-9]+\.supabase\.co$/.test(config.supabaseUrl)
    || !/^sb_publishable_[A-Za-z0-9_-]+$/.test(config.supabasePublishableKey)) {
  throw new Error('Set the project URL and publishable key in public-config.json. Never use a secret key.');
}
await mkdir(path.join(root, 'dist'), { recursive: true });
await build({ entryPoints: [path.join(root, 'src/app.js')], bundle: true, minify: true,
  format: 'esm', target: ['es2022'], outfile: path.join(root, 'dist/app.js'),
  define: { __NEXUS_CONFIG__: JSON.stringify(config) } });
for (const name of ['index.html', 'styles.css']) {
  await copyFile(path.join(root, 'src', name), path.join(root, 'dist', name));
}
const headers = await readFile(path.join(root, 'src/_headers'), 'utf8');
await writeFile(path.join(root, 'dist/_headers'), headers.replaceAll('__SUPABASE_URL__', config.supabaseUrl));
console.log('Dashboard built in dist/. Only public connection settings are bundled.');
