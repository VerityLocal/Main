import test from 'node:test';
import assert from 'node:assert/strict';
import { safeBackend, tokenValid, fileFormat, sourceRanges } from '../common.js';

test('backend credentials can only go to the loopback API', () => {
  assert.equal(safeBackend('http://127.0.0.1:8765'), 'http://127.0.0.1:8765');
  for (const value of ['https://example.com','http://localhost:8000','http://127.0.0.1:8000/path',
    'http://user:password@127.0.0.1:8000','http://127.0.0.1:8000?token=x','http://127.0.0.1.evil.example']) {
    assert.throws(() => safeBackend(value));
  }
});
test('supported formats and explicit safe tokens', () => {
  assert.equal(fileFormat('sample.PDF'), 'pdf'); assert.equal(fileFormat('example.py'), 'python');
  assert.equal(fileFormat('example.js'), 'javascript'); assert.equal(fileFormat('example.txt'), 'text');
  assert.equal(fileFormat('example.exe'), null); assert(!tokenValid('short')); assert(tokenValid('a'.repeat(40)));
});
test('Python code-point source offsets become exact UTF-16 slices', () => {
  const text = '🧪 first line\r\nsecond 🧠 line\n';
  const points = Array.from(text); const left = points.indexOf('s');
  const ranges = sourceRanges(text, [{ source_start:left,source_end:points.length }]);
  assert.equal(text.slice(...ranges[0]), points.slice(left).join(''));
  assert.deepEqual(sourceRanges(text,[{source_start:-1,source_end:3}]),[]);
  assert.deepEqual(sourceRanges(text,[{source_start:0,source_end:999}]),[]);
});
