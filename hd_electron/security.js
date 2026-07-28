const path = require('path');

function parseServerUrl(raw) {
  const url = new URL(raw || 'http://127.0.0.1:5000');
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error('Server URL must use HTTP or HTTPS');
  }
  return url;
}

function parseList(raw, separator = path.delimiter) {
  return String(raw || '')
    .split(separator)
    .map((item) => item.trim())
    .filter(Boolean);
}

function isAllowedPath(candidate, roots) {
  if (!candidate || !Array.isArray(roots) || roots.length === 0) return false;
  const resolved = path.resolve(candidate);
  return roots.some((root) => {
    const allowed = path.resolve(root);
    return resolved === allowed || resolved.startsWith(`${allowed}${path.sep}`);
  });
}

function isAllowedExternalUrl(raw, allowedHosts) {
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' && allowedHosts.includes(url.hostname);
  } catch {
    return false;
  }
}

module.exports = { parseServerUrl, parseList, isAllowedPath, isAllowedExternalUrl };
