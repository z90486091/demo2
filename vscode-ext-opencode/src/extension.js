const vscode = require('vscode');
const http = require('http');

let enabled = true;
let statusBar;
let connections = new Map();
let decorationType;
let decorationBlink;
let ghostTextDecoration;

function activate(context) {
  decorationBlink = vscode.window.createTextEditorDecorationType({
    backgroundColor: new vscode.ThemeColor('editor.wordHighlightTextBackground'),
    isWholeLine: true,
    borderWidth: '0 0 0 3px',
    borderStyle: 'solid',
    borderColor: new vscode.ThemeColor('gitDecoration.addedResourceForeground'),
  });

  context.subscriptions.push(decorationBlink);

  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.command = 'watchdiff.toggle';

  decorationType = vscode.window.createTextEditorDecorationType({
    backgroundColor: new vscode.ThemeColor('diffEditor.insertedLineBackground'),
    isWholeLine: true,
    borderWidth: '0 0 0 3px',
    borderStyle: 'solid',
    borderColor: new vscode.ThemeColor('gitDecoration.addedResourceForeground'),
  });

  ghostTextDecoration = vscode.window.createTextEditorDecorationType({
    isWholeLine: true,
  });

  context.subscriptions.push(decorationType);
  context.subscriptions.push(ghostTextDecoration);
  context.subscriptions.push(statusBar);

  context.subscriptions.push(
    vscode.commands.registerCommand('watchdiff.toggle', () => {
      enabled = !enabled;
      updateStatusBar();
      if (enabled) connectAll();
      else disconnectAll();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('watchdiff.openSettings', () => {
      vscode.commands.executeCommand('workbench.action.openSettings', 'watchdiff');
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(e => {
      if (e.affectsConfiguration('watchdiff')) {
        disconnectAll();
        if (enabled) connectAll();
      }
    })
  );

  connectAll();
  updateStatusBar();
  statusBar.show();
}

function getConfig() {
  const cfg = vscode.workspace.getConfiguration('watchdiff');
  return {
    ports: cfg.get('ports', [4096]),
    username: cfg.get('username', ''),
    password: cfg.get('password', ''),
    watchDir: cfg.get('watchDir', ''),
  };
}

function getEffectiveDir() {
  const { watchDir } = getConfig();
  if (watchDir) return watchDir;
  return vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath || '';
}

function connectAll() {
  const { ports } = getConfig();
  for (const port of connections.keys()) {
    if (!ports.includes(port)) disconnectPort(port);
  }
  for (const port of ports) {
    if (!connections.has(port)) connectPort(port);
  }
}

function disconnectAll() {
  for (const port of connections.keys()) disconnectPort(port);
}

function disconnectPort(port) {
  const conn = connections.get(port);
  if (conn?.req) conn.req.destroy();
  connections.delete(port);
  updateStatusBar();
}

function connectPort(port) {
  const dir = getEffectiveDir();
  const { username, password } = getConfig();
  const query = dir ? `?directory=${encodeURIComponent(dir)}` : '';
  const url = `http://localhost:${port}/event${query}`;

  const headers = { Accept: 'text/event-stream' };
  if (username && password) {
    headers['Authorization'] = 'Basic ' + Buffer.from(`${username}:${password}`).toString('base64');
  }

  connections.set(port, { req: null, status: 'connecting' });
  updateStatusBar();

  const req = http.get(url, { headers }, (res) => {
    if (res.statusCode !== 200) {
      connections.set(port, { req: null, status: 'disconnected' });
      updateStatusBar();
      scheduleReconnect(port, 5000);
      return;
    }

    connections.set(port, { req, status: 'connected' });
    updateStatusBar();

    let buffer = '';
    let sseEvent = '', sseData = '';

    res.on('data', (chunk) => {
      buffer += chunk.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith('event:')) {
          sseEvent = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          sseData = line.slice(5).trim();
        } else if (line === '') {
          if (sseData) handleEvent(sseEvent, sseData, port);
          sseEvent = ''; sseData = '';
        }
      }
    });

    res.on('end', () => {
      connections.set(port, { req: null, status: 'disconnected' });
      updateStatusBar();
      scheduleReconnect(port, 3000);
    });
  });

  req.on('error', () => {
    connections.set(port, { req: null, status: 'disconnected' });
    updateStatusBar();
    scheduleReconnect(port, 5000);
  });

  const existing = connections.get(port);
  if (existing) existing.req = req;
}

function scheduleReconnect(port, delay) {
  setTimeout(() => {
    if (enabled && getConfig().ports.includes(port)) connectPort(port);
  }, delay);
}

function parseHunkRange(patch) {
  const matches = [...patch.matchAll(/@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@/gm)];
  if (!matches.length) return { start: 0, end: 0, changedStart: 0, changedEnd: 0, changedRanges: [], ghostOptions: [] };

  const hunkStart = parseInt(matches[0][1], 10) - 1;
  const count = parseInt(matches[0][2] ?? '1', 10);
  const hunkEnd = hunkStart + Math.max(count - 1, 0);

  let totalStart = hunkStart;
  let totalEnd = hunkEnd;

  const lines = patch.split('\n');
  const changedRanges = [];
  const ghostOptions = [];
  let currentLine = hunkStart;

  // Consecutive '+' lines are buffered and anchored to a SINGLE preceding
  // line (the last real line before the run starts), instead of each line
  // advancing its own anchor by one. Previously each added line anchored
  // itself one line further down than the last, which only happens to be
  // correct for the first line in a run.
  let ghostBuffer = [];
  let ghostAnchorLine = null;

  const flushGhostBuffer = () => {
    if (!ghostBuffer.length) return;
    ghostOptions.push({
      range: new vscode.Range(ghostAnchorLine, 0, ghostAnchorLine, 0),
      renderOptions: {
        after: {
          // U+2028 (line separator) + forced 'pre' whitespace lets a single
          // decoration render multiple stacked lines of ghost text.
          contentText: ghostBuffer.map(t => '  +  ' + t).join('\u2028'),
          color: new vscode.ThemeColor('editorGhostText.foreground'),
          fontStyle: 'italic',
          margin: '0 0 0 16px',
          textDecoration: 'none; white-space: pre;',
        }
      }
    });
    ghostBuffer = [];
    ghostAnchorLine = null;
  };

  for (const line of lines) {
    const match = line.match(/^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@/);
    if (match) {
      flushGhostBuffer();
      currentLine = parseInt(match[1], 10) - 1;
      const cnt = parseInt(match[2] ?? '1', 10);
      totalEnd = currentLine + Math.max(cnt - 1, 0);
      continue;
    }
    if (line.startsWith('+') && !line.startsWith('+++')) {
      const addedText = line.slice(1);
      const range = new vscode.Range(currentLine, 0, currentLine, addedText.length);
      changedRanges.push(range);

      if (ghostAnchorLine === null) ghostAnchorLine = Math.max(0, currentLine - 1);
      ghostBuffer.push(addedText);

      currentLine++;
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      flushGhostBuffer();
      const prev = Math.max(0, currentLine - 1);
      changedRanges.push(new vscode.Range(prev, 0, currentLine, 0));
    } else if (line.startsWith(' ') || (line.length > 0 && !line.startsWith('\\') && !line.startsWith('-') && !line.startsWith('+'))) {
      flushGhostBuffer();
      currentLine++;
    }
  }
  flushGhostBuffer();

  const changedStart = changedRanges[0]?.start.line ?? hunkStart;
  const changedEnd = changedRanges[changedRanges.length - 1]?.end.line ?? hunkStart;

  return { start: totalStart, end: totalEnd, changedStart, changedEnd, changedRanges, ghostOptions };
}

function handleEvent(eventName, dataStr, port) {
  let data;
  try { data = JSON.parse(dataStr); } catch { return; }

  const type = data?.type || eventName;
  const props = data?.properties || data;

  if (type === 'permission.asked') {
    const filePath = props?.metadata?.filepath;
    const patch = props?.metadata?.diff;
    const permissionId = props?.id;
    if (!filePath) return;
    const { start, end, changedStart, changedEnd, changedRanges, ghostOptions } = parseHunkRange(patch || '');

    // Diagnostic: confirm whether ghostOptions is actually populated coming
    // out of parseHunkRange, vs. dropped later in navigateToEdit. Check
    // Output > Extension Host (or Help > Toggle Developer Tools > Console)
    // for these lines. Remove once confirmed.
    console.log(
      '[watchdiff] permission.asked patch length:', (patch || '').length,
      '| changedRanges:', changedRanges.length,
      '| ghostOptions:', ghostOptions.length
    );

    navigateToEdit(filePath, start, end, changedStart, changedEnd, changedRanges, port, permissionId, ghostOptions);
    return;
  }

  if (type === 'file.edited' || type === 'file.watcher.updated') {
    return;
  }

  const filePath = props?.path || props?.file || props?.filename || props?.filePath;
  const startLine = props?.start ?? props?.startLine ?? props?.line;
  const endLine = props?.end ?? props?.endLine;
  if (filePath) navigateToEdit(filePath, startLine, endLine, null, null, [], port, null, []);
}

async function navigateToEdit(filePath, startLine, endLine, changedStart, changedEnd, changedRanges = [], port, permissionId, ghostOptions = []) {
  try {
    const uri = vscode.Uri.file(filePath);
    const doc = await vscode.workspace.openTextDocument(uri);
    const editor = await vscode.window.showTextDocument(doc, { preserveFocus: false, preview: true });

    const start = startLine != null ? Math.max(0, startLine) : 0;
    const end = endLine != null ? Math.min(endLine, doc.lineCount - 1) : start;
    const hunkRange = new vscode.Range(start, 0, end, doc.lineAt(end).text.length);

    editor.revealRange(hunkRange, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    editor.setDecorations(decorationType, changedRanges.length ? changedRanges : [hunkRange]);

    if (ghostOptions.length > 0) {
      // Previously this FILTERED OUT (dropped entirely) any ghost option
      // whose anchor line was >= doc.lineCount, e.g. when the diff's line
      // numbers assume edits/insertions that haven't been written to disk
      // yet (permission.asked fires before the file is updated). That is
      // the one place ghost decorations are treated differently from the
      // highlight decorations above, which have no such filter and get
      // silently clamped by VS Code instead. Clamping here too means
      // ghost text still renders (on the last valid line) instead of
      // vanishing completely.
      const safeGhostOptions = ghostOptions.map(g => {
        const clampedLine = Math.min(g.range.start.line, Math.max(0, doc.lineCount - 1));
        if (clampedLine === g.range.start.line) return g;
        return {
          ...g,
          range: new vscode.Range(clampedLine, 0, clampedLine, 0),
        };
      });
      console.log('[watchdiff] applying ghost decorations:', safeGhostOptions.length, 'of', ghostOptions.length);
      editor.setDecorations(ghostTextDecoration, safeGhostOptions);
    }

    let changedRange;
    if (changedStart != null && changedStart >= 0) {
      const cs = Math.max(0, changedStart);
      const ce = Math.min(changedEnd ?? cs, doc.lineCount - 1);
      changedRange = new vscode.Range(cs, 0, ce, doc.lineAt(ce).text.length);
      editor.selection = new vscode.Selection(changedRange.start, changedRange.end);
      editor.revealRange(changedRange, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    } else {
      editor.selection = new vscode.Selection(hunkRange.start, hunkRange.end);
    }

    const activeRange = (changedStart != null && changedStart >= 0) ? changedRange : hunkRange;

    let on = true;
    const interval = setInterval(() => {
      on = !on;
      editor.setDecorations(decorationBlink, on ? [activeRange] : []);
    }, 300);

    setTimeout(() => {
      editor.setDecorations(decorationType, []);
      editor.setDecorations(ghostTextDecoration, []);
      clearInterval(interval);
      editor.setDecorations(decorationBlink, []);

      if (changedRanges.length > 0) {
        const { username, password } = getConfig();
        const auth = (username && password)
          ? 'Basic ' + Buffer.from(`${username}:${password}`).toString('base64')
          : null;
        vscode.window.showInformationMessage(`Approve edit: ${filePath.split('/').pop()}?`, 'Once', 'Always', 'Reject')
          .then(selection => {
            if (!selection || !permissionId) return;
            const reply = selection === 'Reject' ? 'no' : selection === 'Always' ? 'always' : 'once';
            const body = JSON.stringify({ reply });
            const url = new URL(`http://localhost:${port}/permission/${permissionId}/reply`);
            const headers = { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) };
            if (auth) headers['Authorization'] = auth;
            const req = http.request({ hostname: url.hostname, port: url.port, path: url.pathname, method: 'POST', headers }, () => {});
            req.on('error', () => {});
            req.write(body);
            req.end();
          });
      }
    }, 3000);

  } catch {}
}

function updateStatusBar() {
  if (!enabled) {
    statusBar.text = '$(eye-closed) watchdiff';
    statusBar.tooltip = 'WatchDiff OFF — click to enable';
    statusBar.backgroundColor = undefined;
    return;
  }
  const statuses = [...connections.values()].map(c => c.status);
  const connected = statuses.filter(s => s === 'connected').length;
  const total = statuses.length;
  if (connected === 0) {
    statusBar.text = '$(warning) watchdiff';
    statusBar.tooltip = `WatchDiff: no opencode servers connected\nPorts: ${getConfig().ports.join(', ')}\nClick to toggle`;
    statusBar.backgroundColor = undefined;
  } else {
    statusBar.text = `$(eye) watchdiff ${connected}/${total}`;
    statusBar.tooltip = `WatchDiff: ${connected}/${total} connected\nPorts: ${getConfig().ports.join(', ')}\nClick to toggle`;
    statusBar.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
  }
}

function deactivate() { disconnectAll(); }

module.exports = { activate, deactivate };
