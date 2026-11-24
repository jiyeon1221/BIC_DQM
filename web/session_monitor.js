// DQM sessions persist on the server independently of this browser tab.
let dqmSession = null,
    sessionPollBusy = false,
    sessionLastFile = null;
let sessionPollError = '';
let sessionLogPrevious = null;
const sessionLogMessages = new Map(),
    sessionProgressRows = new Map();
const progressKeys = ['read', 'decode', 'matching', 'sync', 'quality', 'saved', 'plots', 'viewer'];
// The browser selects a mode; thresholds stay in config/aux_cuts.json.
function sessionOptions() {
    return {
        live: field('liveMode').checked,
        aux_cut_mode: field('auxCutMode').value
    };
}
function setupCutControls() {
    field('auxCutMode').addEventListener('change', updateCommandPreview);
}
async function liveAPI(action, body = {}) {
    const response = await fetch('/live/' + action, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'DQM request failed');
    return data;
}
async function startSession(request) {
    const data = await liveAPI('start', request);
    dqmSession = data.session;
    sessionLastFile = null;
    logSessionStatus(data);
    await pollSession();
}
async function displaySessionPlots(files) {
    if (!files.length) return;
    const info = files[0],
        stamp = info.name + ':' + (info.version || info.mtime_ns);
    if (sessionLastFile === stamp) return;
    const existing = [...windows.entries()].filter(([id, w]) => w.filename === info.name);
    await loadFileList(false);
    if (existing.length) {
        const file = await JSROOT.openFile(
            `output/${info.name}?${info.version ? 'v=' + encodeURIComponent(info.version) : 't=' + info.mtime_ns}`
        );
        const keys = (file.fKeys || []).filter((k) => k.fClassName === 'TCanvas');
        const names = new Set(keys.map((k) => k.fName));
        for (const [id, w] of existing) {
            const series =
                w.waveform && findWaveformSeries(file, w.objectName, w.waveform.series.id);
            if (!names.has(w.objectName) && !series) {
                closePlotWindow(id);
                continue;
            }
            w.rootFile = file;
            windows.set(id, w);
            await loadPlotInWindow(id, w.objectName, file, false);
        }
    }
    sessionLog(`[Viewer] Result updated: ${info.name.split('/').pop()}`, 'command-info', 'viewer');
    sessionLastFile = stamp;
}
// Keep current progress in place inside Command log; only lifecycle messages accumulate.
function sessionLog(message, level = 'command-info', key = null) {
    const output = field('commandOutput');
    if (!output) return;
    if (key && sessionLogMessages.get(key) === message) return;
    if (key) sessionLogMessages.set(key, message);
    const follow = output.scrollHeight - output.scrollTop - output.clientHeight < 40;
    const fixed = progressKeys.includes(key);
    let row = fixed ? sessionProgressRows.get(key) : null;
    if (row?.parentNode !== output) row = null;
    const fresh = !row;
    if (fresh) row = document.createElement('div');
    const time = new Date().toLocaleTimeString('en-GB', { hour12: false });
    row.className = level;
    row.textContent = `${time} ${message}`;
    if (fresh) {
        const index = fixed ? progressKeys.indexOf(key) : -1;
        const next = progressKeys
            .slice(index + 1)
            .map((k) => sessionProgressRows.get(k))
            .find((n) => n?.parentNode === output);
        output.insertBefore(row, next || null);
        if (fixed) sessionProgressRows.set(key, row);
    }
    // Keep history bounded without removing the current progress rows.
    while (output.children.length > 2000) output.removeChild(output.children[0]);
    if (follow) output.scrollTop = output.scrollHeight;
}
function logSessionStatus(data) {
    const d = data.decode || {},
        raw = data.raw_decode || d,
        a = data.analysis || {};
    let previous = sessionLogPrevious;
    if (!previous || previous.session !== data.session) {
        previous = null;
        sessionLogMessages.clear();
        for (const row of sessionProgressRows.values())
            if (row.parentNode) row.parentNode.removeChild(row);
        sessionProgressRows.clear();
        sessionLog(
            `[DQM] ${data.profile} Run ${data.run} · ${data.matching === false ? 'Decode → plot' : 'Decode → match → plot'} · ${data.live ? 'Live' : 'Batch'} · session ${data.session}`
        );
    }
    if (!previous && data.cache) {
        const action = {
            reused: 'Reusing saved decoded ROOT',
            seeded: 'Reusing decoded ROOT and continuing from the saved input position',
            shared: 'Reading shared decoding in progress',
            resumed: 'Resuming saved decoding',
            created: 'Decoding run into the shared cache'
        }[data.cache.mode];
        sessionLog(`[Cache] ${action} · Run ${data.run}`);
    }
    if (!previous && data.matching_reasons?.length)
        sessionLog('[Plan] ' + data.matching_reasons.join('; '));
    for (const [stage, entry] of [
        ['Decoder', raw],
        ...(data.matching !== false && data.raw_decode ? [['Matching', d]] : []),
        ['Analysis', a]
    ]) {
        const old =
            stage === 'Decoder'
                ? previous?.raw_decode || previous?.decode
                : stage === 'Matching'
                  ? previous?.decode
                  : previous?.analysis;
        if (
            ['complete', 'paused', 'stopped', 'caught_up'].includes(entry.status) &&
            entry.status !== old?.status
        )
            sessionLog(`[${stage}] ${entry.status === 'paused' ? 'stopped' : entry.status}`);
        if (entry.error && entry.error !== old?.error)
            sessionLog(`[${stage}] ${entry.error}`, 'command-error');
    }
    // Paths are useful on discovery, not on every progress update.
    for (const input of d.inputs || []) {
        const ready = (input.bytes || 0) > 0 || (input.records || 0) > 0;
        sessionLog(
            `[Input] ${ready ? 'Detected' : 'Waiting for data'}: ${input.path}`,
            'command-info',
            'input:' + input.path
        );
        if (input.bad || input.late || input.duplicates)
            sessionLog(
                `[Input quality] ${input.path.split('/').pop()} · bad ${input.bad || 0} · late ${input.late || 0} · duplicates ${input.duplicates || 0}`,
                'command-info',
                'quality:' + input.path
            );
    }
    const state = raw.status === 'paused' ? 'stopped' : raw.status || 'starting';
    const progress = raw.input_progress;
    let decodeState =
        state === 'waiting'
            ? data.live
                ? 'waiting for more input'
                : 'waiting for input / matching'
            : state;
    if (state === 'running') {
        decodeState =
            {
                reading: 'reading / decoding input',
                collecting: 'collecting decoded events',
                matching: 'matching decoded events',
                writing_root: 'writing ROOT file',
                checkpointing: 'saving processing state'
            }[raw.phase] || 'reading / matching / saving';
        if (
            progress?.complete &&
            !data.live &&
            ['reading', 'matching', 'collecting', undefined].includes(raw.phase)
        )
            decodeState =
                data.matching === false
                    ? 'input read complete; draining decoded events'
                    : 'input read complete; finishing matching';
    }
    if (state === 'complete' && data.cache?.mode === 'reused')
        decodeState = 'complete (cached ROOT)';
    const gb = (bytes) => (bytes / 1e9).toFixed(3) + ' GB';
    if (progress) {
        const fraction =
            progress.percent == null ? 'total unknown' : progress.percent.toFixed(1) + '%';
        sessionLog(
            `[Read] ${fraction} · ${gb(progress.read_bytes)} / ${gb(progress.total_bytes)} · files at EOF ${progress.files_read}/${progress.total_files}${progress.missing_files ? ' · missing ' + progress.missing_files + ' files' : ''}${data.live ? ' · current file sizes; Live total is open' : ''}`,
            'command-progress',
            'read'
        );
    }
    const total = raw.decoded_records ?? (raw.decoded_nk || 0) + (raw.decoded_rc || 0);
    const batch =
        data.live && !['complete', 'stopped', 'error'].includes(state)
            ? ` · next update ${raw.batch_decoded || 0}/${raw.batch_size || 1000}`
            : '';
    sessionLog(
        `[Decode] ${decodeState} · processed ${total} source events (NK ${raw.decoded_nk || 0}, RC ${raw.decoded_rc || 0})${batch}`,
        state === 'error' ? 'command-error' : 'command-progress',
        'decode'
    );
    if (data.matching !== false) {
        sessionLog(
            `[Matching] matched ${d.matched || 0} events · saved ${d.committed || 0} · ROOT files ${d.chunks || 0} · waiting NK ${d.waiting_nk || 0}, RC ${d.waiting_rc || 0}`,
            'command-progress',
            'matching'
        );
        if (d.clock_matching)
            sessionLog(
                `[Sync] ${d.sync_locked ? 'Clock matching ready' : 'Waiting for clock synchronization'}`,
                'command-progress',
                'sync'
            );
        if (d.nk_unmatched || d.rc_unmatched || d.nk_join_dropped_parts)
            sessionLog(
                `[Quality] unmatched NK ${d.nk_unmatched || 0}, RC ${d.rc_unmatched || 0} · NK join drops ${d.nk_join_dropped_parts || 0}`,
                'command-info',
                'quality'
            );
    } else {
        sessionLog(
            `[ROOT] saved ${d.committed || 0} decoded records · files ${d.chunks || 0}`,
            'command-progress',
            'saved'
        );
    }
    let plotState =
        {
            starting: 'starting',
            waiting_for_decode: 'waiting for decoding to finish',
            replaying: 'preparing plots',
            running: 'drawing',
            waiting: 'waiting for decoded data',
            caught_up: 'finished available data',
            complete: 'complete',
            stopped: 'stopped',
            error: 'error'
        }[a.status] || 'starting';
    if (
        data.live &&
        a.status === 'running' &&
        !a.phase &&
        (a.chunks || 0) > 0 &&
        a.chunks >= d.chunks
    )
        plotState = 'up to date; waiting for next ROOT';
    const totalChunks = a.total_chunks ?? d.chunks ?? 0;
    if (a.status === 'running' && a.phase === 'reading_root')
        plotState = `reading ROOT ${a.current_chunk}/${totalChunks}; applying cuts / filling histograms`;
    if (a.status === 'running' && a.phase === 'saving_plots')
        plotState = 'rendering canvases / saving plot file';
    if (a.status === 'waiting_for_decode') {
        sessionLog(
            '[Plots] waiting for decoding, matching and ROOT writing to finish (Batch); drawing has not started',
            'command-progress',
            'plots'
        );
    } else {
        const finalTotal = d.status === 'complete';
        const percent =
            finalTotal && totalChunks > 0
                ? ` (${((100 * (a.chunks || 0)) / totalChunks).toFixed(1)}% read)`
                : '';
        sessionLog(
            `[Plots] ${plotState} · ${finalTotal ? 'total' : 'available'} ROOT files ${a.chunks || 0}/${totalChunks}${percent} · read ${a.seen || 0} entries · cut passed ${a.passed || 0}/${a.evaluated ?? a.seen ?? 0} · plotted ${a.plotted || 0}`,
            a.status === 'error' ? 'command-error' : 'command-progress',
            'plots'
        );
    }
    sessionLogPrevious = data;
}
async function pollSession() {
    if (sessionPollBusy) return;
    sessionPollBusy = true;
    try {
        const response = await fetch('/live/status');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Cannot read DQM status');
        if (!data.session) {
            if (sessionPollError) {
                sessionLog('[DQM] Monitoring resumed');
                sessionPollError = '';
            }
            return;
        }
        if (dqmSession !== data.session) {
            dqmSession = data.session;
            sessionLastFile = null;
        }
        logSessionStatus(data);
        await displaySessionPlots(data.files);
        if (sessionPollError) {
            sessionLog('[DQM] Monitoring resumed');
            sessionPollError = '';
        }
    } catch (error) {
        if (error.message !== sessionPollError)
            sessionLog(`[DQM] ${error.message}`, 'command-error');
        sessionPollError = error.message;
    } finally {
        sessionPollBusy = false;
    }
}
function setupSessionForm() {
    field('liveMode').addEventListener('change', updateCommandPreview);
    setupCutControls();
    pollSession();
    setInterval(pollSession, 2000);
}
