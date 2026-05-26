const vscode = require('vscode');
const { execFile } = require('child_process');
const path = require('path');

const diagnosticCollection = vscode.languages.createDiagnosticCollection('rtlsense');
let statusBar;
let outputChannel;

function getRtlsenseBin(venvPath) {
    if (venvPath) return path.join(venvPath, 'bin', 'rtlsense');
    const home = process.env.HOME || '';
    const candidates = [
        path.join(home, 'silimate_demo', 'venv', 'bin', 'rtlsense'),
        '/opt/homebrew/bin/rtlsense',
        'rtlsense',
    ];
    return candidates[0];
}

function analyzeFile(document) {
    if (!document) return;
    const config = vscode.workspace.getConfiguration('rtlsense');
    if (!config.get('enabled')) return;

    const filePath = document.fileName;
    if (!/\.(v|sv)$/.test(filePath)) return;

    const clock = config.get('clock') || '500MHz';
    const venvPath = config.get('venvPath') || '';
    const rtlsense = getRtlsenseBin(venvPath);

    statusBar.text = '$(sync~spin) RTLSense: analyzing...';
    statusBar.show();

    const args = ['check', filePath, '--clock', clock, '--json'];
    outputChannel.appendLine(`[RTLSense] Running: ${rtlsense} ${args.join(' ')}`);

    const env = Object.assign({}, process.env, {
        PATH: `/opt/homebrew/bin:/usr/local/bin:${process.env.PATH || ''}`,
    });

    const folders = vscode.workspace.workspaceFolders;
    const cwd = folders && folders.length > 0
        ? folders[0].uri.fsPath
        : require('path').dirname(filePath);

    execFile(rtlsense, args,
        { timeout: 60000, env, cwd },
        (err, stdout, stderr) => {
            statusBar.hide();
            diagnosticCollection.delete(document.uri);

            outputChannel.appendLine(`[RTLSense] exit code: ${err ? err.code : 0}`);
            outputChannel.appendLine(`[RTLSense] stdout: ${stdout.slice(0, 500)}`);
            if (stderr) outputChannel.appendLine(`[RTLSense] stderr: ${stderr.slice(0, 500)}`);

            let data;
            try {
                data = JSON.parse(stdout);
            } catch (e) {
                outputChannel.appendLine(`[RTLSense] JSON parse error: ${e.message}`);
                let msg;
                if (err && err.code === 'ENOENT') {
                    msg = `RTLSense: binary not found at ${rtlsense}`;
                } else if (err && !stdout) {
                    const stderrClean = stderr.replace(/\x1b\[[0-9;]*m/g, '');
                    const errorLine = stderrClean.split('\n').find(l => /error|Error|failed|Failed/.test(l) && l.trim());
                    msg = errorLine ? errorLine.trim() : `RTLSense: exit ${err.code} — check Output > RTLSense`;
                } else {
                    msg = `RTLSense: unexpected output — check Output > RTLSense`;
                }
                const range = new vscode.Range(0, 0, 0, 999);
                const diag = new vscode.Diagnostic(range, msg, vscode.DiagnosticSeverity.Warning);
                diag.source = 'RTLSense';
                diagnosticCollection.set(document.uri, [diag]);
                statusBar.text = `$(warning) RTLSense: error`;
                statusBar.color = new vscode.ThemeColor('terminal.ansiYellow');
                statusBar.show();
                setTimeout(() => statusBar.hide(), 8000);
                return;
            }
            outputChannel.appendLine(`[RTLSense] parsed OK — ${(data.diagnostics || []).length} diagnostics`);

            const diagnostics = [];
            for (const d of (data.diagnostics || [])) {
                const line = Math.max(0, (d.line || 1) - 1);
                const range = new vscode.Range(line, 0, line, 999);

                const severity = d.severity === 'error'
                    ? vscode.DiagnosticSeverity.Error
                    : vscode.DiagnosticSeverity.Warning;

                const slackStr = d.slack != null ? `${d.slack.toFixed(3)}ns` : '?';
                const depthStr = d.logic_depth != null ? `${d.logic_depth} levels` : '';
                const delayStr = d.path_delay != null ? `${d.path_delay.toFixed(3)}ns path` : '';

                let msg = `RTLSense: timing violation — slack ${slackStr}`;
                if (depthStr) msg += `, ${depthStr}`;
                if (delayStr) msg += `, ${delayStr}`;
                if (d.suggestion) msg += `\n💡 ${d.suggestion}`;

                const diag = new vscode.Diagnostic(range, msg, severity);
                diag.source = 'RTLSense';
                diag.code = `${d.startpoint} → ${d.endpoint}`;
                diagnostics.push(diag);
            }

            diagnosticCollection.set(document.uri, diagnostics);

            const wns = data.wns != null ? data.wns.toFixed(3) : '?';
            const count = diagnostics.length;
            if (count === 0) {
                statusBar.text = '$(check) RTLSense: timing met';
                statusBar.color = new vscode.ThemeColor('terminal.ansiGreen');
            } else {
                statusBar.text = `$(error) RTLSense: ${count} violation${count > 1 ? 's' : ''} WNS ${wns}ns`;
                statusBar.color = new vscode.ThemeColor('terminal.ansiRed');
            }
            statusBar.show();
            setTimeout(() => statusBar.hide(), 8000);
        }
    );
}

function activate(context) {
    outputChannel = vscode.window.createOutputChannel('RTLSense');
    context.subscriptions.push(outputChannel);
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    context.subscriptions.push(statusBar);
    context.subscriptions.push(diagnosticCollection);

    // Analyze on save
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(analyzeFile)
    );

    // Analyze when switching to a Verilog file
    context.subscriptions.push(
        vscode.window.onDidChangeActiveTextEditor(editor => {
            if (editor) analyzeFile(editor.document);
        })
    );

    // Manual command
    context.subscriptions.push(
        vscode.commands.registerCommand('rtlsense.analyze', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) analyzeFile(editor.document);
        })
    );

    // Analyze the currently active file on startup
    if (vscode.window.activeTextEditor) {
        analyzeFile(vscode.window.activeTextEditor.document);
    }

    outputChannel.appendLine('[RTLSense] Extension activated');
}

function deactivate() {
    diagnosticCollection.clear();
}

module.exports = { activate, deactivate };
