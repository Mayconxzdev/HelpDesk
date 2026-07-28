const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { isAllowedExternalUrl, isAllowedPath, parseServerUrl } = require('../security');

test('accepts HTTP(S) server URLs and rejects local file URLs', () => {
  assert.equal(parseServerUrl('https://helpdesk.example.com').protocol, 'https:');
  assert.throws(() => parseServerUrl('file:///tmp/index.html'));
});

test('update URL must be HTTPS and use an allowlisted host', () => {
  assert.equal(isAllowedExternalUrl('https://github.com/org/repo/releases', ['github.com']), true);
  assert.equal(isAllowedExternalUrl('http://github.com/file.exe', ['github.com']), false);
  assert.equal(isAllowedExternalUrl('https://evil.example/file.exe', ['github.com']), false);
});

test('folder access stays inside configured roots', () => {
  const root = path.resolve('/tmp/helpdesk-shares');
  assert.equal(isAllowedPath(path.join(root, 'team'), [root]), true);
  assert.equal(isAllowedPath(path.resolve('/tmp/other'), [root]), false);
});
