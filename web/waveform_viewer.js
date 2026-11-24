// Browse ROOT waveforms for one channel group in event order.
const waveformSeriesCache = new WeakMap();

function waveformSeries(file) {
    if (waveformSeriesCache.has(file)) return waveformSeriesCache.get(file);
    const groups = new Map();
    const keys = new Map((file.fKeys || []).map((key) => [key.fName, key]));
    for (const key of keys.values()) {
        const match = /^c_Waveform_(\d+)_group(\d+)_(\d+)$/.exec(key.fName);
        if (!match || key.fClassName !== 'TCanvas') continue;
        const title = rootTitleText(key.fTitle || '');
        const label = title.split(' · Waveform · ')[0];
        const caption = label && label !== key.fName ? label : `Group ${Number(match[2]) + 1}`;
        const id = `${caption}\0${match[3]}`;
        if (!groups.has(id)) {
            groups.set(id, { id, label: caption, page: Number(match[3]), frames: [] });
        }
        groups.get(id).frames.push({ name: key.fName, event: match[1], title });
    }
    const result = [...groups.values()];
    for (const group of result) {
        group.frames.sort((a, b) =>
            BigInt(a.event) < BigInt(b.event) ? -1 : BigInt(a.event) > BigInt(b.event) ? 1 : 0
        );
    }
    waveformSeriesCache.set(file, result);
    return result;
}

function findWaveformSeries(file, name, id) {
    const groups = waveformSeries(file);
    return (
        (id && groups.find((group) => group.id === id)) ||
        groups.find((group) => group.frames.some((frame) => frame.name === name))
    );
}

function waveformSidebarKeys(file) {
    const hidden = new Set(
        waveformSeries(file).flatMap((group) => group.frames.slice(1).map((frame) => frame.name))
    );
    return (file.fKeys || []).filter((key) => !hidden.has(key.fName));
}

function waveformSidebarLabel(file, name) {
    const group = findWaveformSeries(file, name);
    if (!group) return plotKeyLabel(file, name);
    const page = group.page ? ` · Page ${group.page + 1}` : '';
    return `${group.label} · Waveform${page} · ${group.frames.length} events`;
}

function updateWaveformControls(data) {
    const state = data.waveform;
    const { previous, next, play, slider, label } = state.controls;
    const last = state.series.frames.length - 1;
    previous.disabled = state.busy || state.index === 0;
    next.disabled = state.busy || state.index === last;
    play.disabled = last === 0;
    play.textContent = state.playing ? 'Pause' : 'Play';
    slider.disabled = state.busy || last === 0;
    slider.max = String(last);
    slider.value = String(state.index);
    label.textContent = `${state.index + 1} / ${last + 1}`;
}

function stopWaveformPlayback(data) {
    const state = data.waveform;
    if (!state) return;
    clearTimeout(state.timer);
    state.timer = null;
    state.playing = false;
    updateWaveformControls(data);
}

function disposeWaveformWindow(data) {
    if (!data.waveform) return;
    stopWaveformPlayback(data);
    data.waveform.closed = true;
    ++data.waveform.version;
    JSROOT.cleanup(data.element.querySelector('.plot-window-body'));
}

function scheduleWaveformPlayback(windowId) {
    const data = windows.get(windowId);
    const state = data?.waveform;
    if (!state || !state.playing || state.busy || state.closed) return;
    clearTimeout(state.timer);
    if (state.index === state.series.frames.length - 1) {
        stopWaveformPlayback(data);
        return;
    }
    state.timer = setTimeout(() => changeWaveformFrame(windowId, state.index + 1), 500);
}

function changeWaveformFrame(windowId, index) {
    const data = windows.get(windowId);
    if (!data?.waveform || data.waveform.busy) return;
    const state = data.waveform;
    state.index = Math.max(0, Math.min(state.series.frames.length - 1, Number(index)));
    data.objectName = state.series.frames[state.index].name;
    return renderWaveform(windowId);
}

function setupWaveformControls(windowId, data, series) {
    const bar = document.createElement('div');
    bar.className = 'waveform-navigation';
    const controls = {};
    for (const [key, text] of [
        ['previous', '◀'],
        ['play', 'Play'],
        ['next', '▶']
    ]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = text;
        button.setAttribute(
            'aria-label',
            { previous: 'Previous event', play: 'Play or pause waveforms', next: 'Next event' }[key]
        );
        controls[key] = button;
        bar.appendChild(button);
    }
    controls.slider = document.createElement('input');
    controls.slider.type = 'range';
    controls.slider.min = '0';
    controls.slider.step = '1';
    controls.slider.setAttribute('aria-label', 'Waveform event');
    controls.label = document.createElement('span');
    bar.append(controls.slider, controls.label);
    data.element.insertBefore(bar, data.element.querySelector('.plot-window-resize-handle'));
    data.waveform = {
        series,
        index: 0,
        controls,
        playing: false,
        busy: false,
        version: 0,
        timer: null,
        closed: false
    };
    controls.previous.addEventListener('click', () =>
        changeWaveformFrame(windowId, data.waveform.index - 1)
    );
    controls.next.addEventListener('click', () =>
        changeWaveformFrame(windowId, data.waveform.index + 1)
    );
    controls.slider.addEventListener('input', () =>
        changeWaveformFrame(windowId, controls.slider.value)
    );
    controls.play.addEventListener('click', () => {
        if (data.waveform.playing) return stopWaveformPlayback(data);
        data.waveform.playing = true;
        updateWaveformControls(data);
        if (!data.waveform.busy && data.waveform.index === data.waveform.series.frames.length - 1) {
            changeWaveformFrame(windowId, 0);
        } else {
            scheduleWaveformPlayback(windowId);
        }
    });
}

// Serialize reads and draws, keeping the newest ROOT snapshot during overlapping updates.
function renderWaveform(windowId) {
    const data = windows.get(windowId);
    const state = data.waveform;
    ++state.version;
    if (state.busy) return state.rendering;
    state.busy = true;
    clearTimeout(state.timer);
    updateWaveformControls(data);
    state.rendering = (async () => {
        const body = data.element.querySelector('.plot-window-body');
        try {
            let rendered;
            do {
                rendered = state.version;
                const file = data.rootFile;
                const frame = state.series.frames[state.index];
                const object = await file.readObject(frame.name);
                if (state.closed) return;
                if (rendered !== state.version) continue;
                if (!object) throw new Error('Waveform event not found');
                JSROOT.cleanup(body);
                body.replaceChildren();
                await JSROOT.draw(body, object, '');
                if (state.closed) {
                    JSROOT.cleanup(body);
                    return;
                }
                if (rendered === state.version) {
                    data.element.querySelector('.plot-window-title').textContent = rootTitleText(
                        object.fTitle || frame.title || frame.name
                    );
                    updateWaveformControls(data);
                    if (typeof updateEnlargeButtons === 'function') updateEnlargeButtons();
                }
            } while (rendered !== state.version);
        } catch (error) {
            if (!state.closed) {
                body.textContent = `Unable to draw waveform: ${error.message || error}`;
                stopWaveformPlayback(data);
            }
        } finally {
            state.busy = false;
            if (!state.closed) {
                updateWaveformControls(data);
                scheduleWaveformPlayback(windowId);
            }
        }
    })();
    return state.rendering;
}

async function loadWaveformInWindow(windowId, objectName, file, forceReload = false) {
    const data = windows.get(windowId);
    const request = (data.waveformLoadVersion = (data.waveformLoadVersion || 0) + 1);
    if (forceReload && data.filename) {
        try {
            file = await JSROOT.openFile(`output/${data.filename}?t=${Date.now()}`);
        } catch (_) {
            // Keep the current file if the new snapshot cannot be read.
        }
        if (windows.get(windowId) !== data || request !== data.waveformLoadVersion) return;
    }
    const series = findWaveformSeries(file, objectName, data.waveform?.series.id);
    if (!series) return;
    if (!data.waveform) setupWaveformControls(windowId, data, series);
    const state = data.waveform;
    const index = series.frames.findIndex((frame) => frame.name === objectName);
    state.series = series;
    state.index = index < 0 ? Math.min(state.index, series.frames.length - 1) : index;
    data.rootFile = file;
    data.objectName = series.frames[state.index].name;
    return renderWaveform(windowId);
}
