/* Parse all tracked JS/TS, including modules excluded from the active UI builds. */
'use strict';
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const ts = require(path.join(root, 'frontend/node_modules/typescript'));
const files = execFileSync('git', ['ls-files', '-z'], { cwd: root }).toString().split('\0')
  .filter(n => /\.(?:[cm]?[jt]s|[jt]sx)$/.test(n));
const diagnostics = [];
for (const name of files) {
  const text = fs.readFileSync(path.join(root, name), 'utf8');
  if (/\.d\.[cm]?ts$/.test(name)) {
    const source = ts.createSourceFile(name, text, ts.ScriptTarget.Latest, true);
    for (const d of source.parseDiagnostics) diagnostics.push({ path: name, code: d.code,
      message: ts.flattenDiagnosticMessageText(d.messageText, '\n') });
    continue;
  }
  // The compiler reports illegal TypeScript constructs in JavaScript as well as parse errors.
  const result = ts.transpileModule(text, { fileName: name, reportDiagnostics: true,
    compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.Preserve, allowJs: true } });
  for (const d of result.diagnostics || []) {
    if (d.category === ts.DiagnosticCategory.Error) diagnostics.push({ path: name, code: d.code,
      message: ts.flattenDiagnosticMessageText(d.messageText, '\n') });
  }
}
console.log(JSON.stringify({ files: files.length, diagnostics, scope: 'Syntax only; types, imports, runtime behavior and lint have separate gates.' }, null, 2));
process.exitCode = diagnostics.length ? 1 : 0;
