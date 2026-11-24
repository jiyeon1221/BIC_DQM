// ROOT keys remain the lookup IDs; captions describe the detector actually drawn.
const plotLabelCache = new WeakMap();
function rootTitleText(text) {
    // JSROOT's TString reader exposes UTF-8 bytes as Latin-1 characters.
    // Decode only valid byte sequences; already-Unicode and legacy Latin-1 stay intact.
    return String(text).replace(/[\u00c2-\u00f4][\u0080-\u00bf]+/g, (bytes) => {
        try {
            return new TextDecoder('utf-8', { fatal: true }).decode(
                Uint8Array.from(bytes, (c) => c.charCodeAt(0))
            );
        } catch (_) {
            return bytes;
        }
    });
}
function plotKeyLabel(file, name, object) {
    const labels = plotLabelCache.get(file)?.labels;
    if (labels?.has(name)) return labels.get(name);
    const key = (file.fKeys || []).find((k) => k.fName === name);
    const rawTitle = object?.fTitle || key?.fTitle;
    const title = rawTitle ? rootTitleText(rawTitle) : '';
    return title && title !== name && !/\bc_\d+_draw_|\bc_Waveform_/.test(title) ? title : name;
}
function plotLabelHtml(text) {
    return String(text).replace(
        /[&<>"']/g,
        (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
    );
}
function preparePlotLabels(file) {
    if (plotLabelCache.has(file)) return plotLabelCache.get(file).ready;
    const entry = { labels: new Map() };
    plotLabelCache.set(file, entry);
    entry.ready = (async () => {
        if (!(file.fKeys || []).some((k) => k.fName === 'analysis_json') || !file.readObject)
            return;
        try {
            const metadata = await file.readObject('analysis_json');
            const analysis = JSON.parse(metadata.fTitle);
            // Legacy matched files used arbitrary pages of 33. Describe all regions
            // present on that page; only newly drawn files have spatial canvases.
            for (const key of file.fKeys) {
                const match =
                    /^c_(\d+)_(draw_(?:intADC|peakADC|avg|overlay|heatmap|AUX)|DWC)_(\d+)$/.exec(
                        key.fName
                    );
                if (!match) continue;
                const job = analysis.jobs?.[Number(match[1])];
                if (!job) continue;
                const page = Number(match[3]),
                    exe = match[2];
                let names = job.channels || [];
                if (exe === 'draw_AUX' || exe === 'DWC') {
                    entry.labels.set(
                        key.fName,
                        ['DWC1', 'DWC2', ...names.filter((n) => /^CC\d+$/.test(n))].join(', ')
                    );
                    continue;
                }
                const heatmap = exe === 'draw_heatmap';
                const pages = Math.ceil(names.length / 33);
                if (!heatmap) names = names.slice(page * 33, (page + 1) * 33);
                const regions = [
                    ...new Set(
                        names.map((n) => {
                            const m = /^(SFIL|Bulk)(\d+)_(xm|xp)_/.exec(n);
                            return m
                                ? `${m[1]}${analysis.type === 'module' ? m[2] : ''} ${m[3]}`
                                : n;
                        })
                    )
                ];
                const metric =
                    {
                        draw_intADC: 'IntADC',
                        draw_peakADC: 'PeakADC',
                        draw_avg: 'Avg',
                        draw_overlay: 'Overlay'
                    }[exe] || analysis.method;
                entry.labels.set(
                    key.fName,
                    `${regions.join(', ')} · ${heatmap ? 'Heatmap (' + metric + ')' : metric}${!heatmap && pages > 1 ? ` · ${page + 1}/${pages}` : ''}`
                );
            }
        } catch (_) {
            /* Older standalone ROOT files need no analysis metadata. */
        }
    })();
    return entry.ready;
}

// The server reads the selected .h mapping and chooses each channel's reader.
const ALL_METHODS = ['IntADC', 'PeakADC', 'Avg', 'Overlay', 'Waveform'];
const TYPE_INFO = {
    single: { label: 'Channels:', methods: ALL_METHODS },
    layer: { label: 'Layer (height y):', methods: ['IntADC', 'PeakADC'] },
    heatmap: { methods: ['IntADC', 'PeakADC'] },
    full: { methods: ['IntADC', 'PeakADC'] }
};
let PROFILE_ENTRIES = {},
    MAPPING_CHANNELS = null,
    MAPPING_MODULES = null;
let previewVersion = 0;
let mappingChoicesKey = null;
const field = (id) => document.getElementById(id);
function selectedProfile() {
    return field('systemSelect').value;
}
function availableMethods(profile, type) {
    return profile === 'RCDAQ' && type === 'single'
        ? [...TYPE_INFO.single.methods, 'TOA/TOT']
        : TYPE_INFO[type].methods;
}
function timingSelection() {
    return (
        selectedProfile() === 'RCDAQ' &&
        field('typeSelect').value === 'single' &&
        ['TOA/TOT'].includes(field('methodSelect').value)
    );
}
async function loadMappingChannels() {
    const response = await fetch('/channels');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    PROFILE_ENTRIES = data.profiles;
    const entries = Object.values(PROFILE_ENTRIES).flat();
    MAPPING_CHANNELS = new Set(entries.map((e) => e.name));
    MAPPING_MODULES = [...new Set(entries.filter((e) => e.det >= 0).map((e) => e.module))];
}
function updateFormFields() {
    const type = field('typeSelect').value,
        info = TYPE_INFO[type];
    const entries = PROFILE_ENTRIES[selectedProfile()] || [];
    const layers = [
        ...new Set(
            entries
                .map((e) => {
                    const detector = { 0: 'SFIL', 1: 'Bulk' }[e.det];
                    return detector && Number.isInteger(e.y) && e.y >= 0
                        ? `${detector}_y${e.y}`
                        : null;
                })
                .filter(Boolean)
        )
    ].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    field('moduleLabel').textContent = info.label || 'Selection:';
    field('moduleInput').disabled = !info.label;
    field('moduleInput').placeholder =
        type === 'layer'
            ? layers.join(', ')
            : type === 'single'
              ? 'Exact channel names, separated by spaces'
              : 'All matching channels in this mapping';
    const method = field('methodSelect');
    const methods = availableMethods(selectedProfile(), type);
    method.disabled = !methods.length;
    Array.from(method.options).forEach((o) => {
        o.disabled = !methods.includes(o.value);
        if (['TOA/TOT'].includes(o.value)) o.hidden = o.disabled;
    });
    if (methods.length && !methods.includes(method.value)) method.value = methods[0];
    field('auxCheck').disabled = false;
    field('auxCutMode').disabled = false;
    const waveform = !method.disabled && method.value === 'Waveform';
    field('maxEventLabel').textContent = waveform ? 'Events (Waveform):' : 'Max Event:';
    field('maxEventInput').placeholder = 'Default: -1 (all events)';
    field('maxEventInput').removeAttribute('max');
    const choices =
        type === 'layer'
            ? layers
            : entries.filter((e) => !timingSelection() || e.daq === 'GCROC').map((e) => e.name);
    // Keep the native suggestion popup open while the user types.
    const choicesKey = JSON.stringify(choices);
    if (choicesKey !== mappingChoicesKey) {
        field('mappingChoices').replaceChildren(
            ...choices.map((name) => {
                const option = document.createElement('option');
                option.value = name;
                return option;
            })
        );
        mappingChoicesKey = choicesKey;
    }
}
function commandRequest() {
    return {
        profile: selectedProfile(),
        run: field('runNumber').value,
        type: field('typeSelect').value,
        method: field('methodSelect').disabled ? 'IntADC' : field('methodSelect').value,
        channels: field('moduleInput').value.trim(),
        count: field('maxEventInput').value,
        first: 0,
        aux: field('auxCheck').checked,
        ...sessionOptions()
    };
}
async function getPlan(request) {
    const response = await fetch('/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Cannot build command');
    return result;
}
async function updateCommandPreview() {
    const version = ++previewVersion;
    updateFormFields();
    field('commandPreviewLabel').textContent = 'Processing plan:';
    field('mappingRoute').textContent = '';
    if (!field('runNumber').value) {
        field('commandPreview').textContent = 'Enter a run number and selection.';
        return;
    }
    try {
        const plan = await getPlan(commandRequest());
        if (version !== previewVersion) return;
        field('commandPreview').textContent = plan.command;
        field('mappingRoute').textContent =
            `${plan.route} → ${plan.analysis.method}` +
            (plan.notes.length ? '\n' + plan.notes.join('\n') : '');
        field('moduleInput').classList.remove('invalid');
    } catch (error) {
        if (version !== previewVersion) return;
        field('commandPreview').textContent = error.message;
    }
}
async function executeMonitCommand() {
    const request = commandRequest();
    try {
        await getPlan(request);
        await startSession(request);
    } catch (error) {
        addToOutput(error.message, 'command-error');
    }
}
function setupMonitForm() {
    setupSessionForm();
    for (const id of ['runNumber', 'moduleInput', 'maxEventInput'])
        field(id).addEventListener('input', updateCommandPreview);
    field('typeSelect').addEventListener('change', () => {
        // A previous single-channel name would filter out every layer suggestion.
        field('moduleInput').value = '';
        updateCommandPreview();
    });
    for (const id of ['methodSelect', 'auxCheck'])
        field(id).addEventListener('change', updateCommandPreview);
    field('systemSelect').addEventListener('change', () => {
        field('auxCheck').checked = selectedProfile() === 'RCDAQ';
        updateCommandPreview();
    });
    field('executeMonitBtn').addEventListener('click', executeMonitCommand);
    loadMappingChannels()
        .then(() => {
            updateCommandPreview();
            refreshFileSummaries();
        })
        .catch((error) => addToOutput(error.message, 'command-error'));
    updateFormFields();
}
async function showGeneratedFiles(files) {
    await loadFileList(false);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const gifs = files.filter((f) => f.type === 'gif');
    if (gifs.length) {
        gifs.forEach((f) => createGifWindow(f.name));
    } else {
        for (const info of files.filter((f) => f.type === 'root')) {
            try {
                const file = await JSROOT.openFile(`output/${info.name}?t=${info.mtime_ns}`);
                for (const key of (file.fKeys || []).filter((k) => k.fClassName === 'TCanvas')) {
                    createPlotWindow(key.fName, file, info.name);
                }
            } catch (error) {
                addToOutput(`Cannot display ${info.name}: ${error}`, 'command-error');
            }
        }
    }
}
