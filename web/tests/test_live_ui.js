// Run with node; tests the browser request and window-update contract without a DOM engine.
const fs = require('node:fs'),
    vm = require('node:vm'),
    assert = require('node:assert/strict');
const elements = {};
for (const id of [
    'systemSelect',
    'runNumber',
    'typeSelect',
    'methodSelect',
    'moduleInput',
    'maxEventInput',
    'auxCheck',
    'liveMode',
    'auxCutMode',
    'commandOutput'
])
    elements[id] = { value: '', checked: false, disabled: false };
Object.assign(elements.systemSelect, { value: 'RCDAQ' });
elements.runNumber.value = '1086';
elements.typeSelect.value = 'single';
elements.methodSelect.value = 'Avg';
elements.moduleInput.value = 'SFIL6_xm_y2';
elements.liveMode.checked = true;
elements.auxCutMode.value = 'none';
class LogNode {
    constructor() {
        this.children = [];
        this.parentNode = null;
        this.textContent = '';
        this.scrollTop = 0;
        this.scrollHeight = 100;
        this.clientHeight = 100;
        this.value = '';
        this.checked = false;
        this.disabled = false;
        this.listeners = {};
    }
    set id(value) {
        this._id = value;
        elements[value] = this;
    }
    get id() {
        return this._id;
    }
    replaceChildren(...nodes) {
        this.children.forEach((n) => (n.parentNode = null));
        this.children = [];
        this.append(...nodes);
    }
    append(...nodes) {
        nodes.forEach((n) => this.appendChild(n));
    }
    addEventListener(type, fn) {
        this.listeners[type] = fn;
    }
    insertBefore(node, next) {
        if (!next) return this.appendChild(node);
        if (node.parentNode) node.parentNode.removeChild(node);
        this.children.splice(this.children.indexOf(next), 0, node);
        node.parentNode = this;
        return node;
    }
    removeChild(node) {
        this.children.splice(this.children.indexOf(node), 1);
        node.parentNode = null;
    }
    appendChild(node) {
        if (node.parentNode) {
            const a = node.parentNode.children;
            a.splice(a.indexOf(node), 1);
        }
        this.children.push(node);
        node.parentNode = this;
        return node;
    }
}
elements.commandOutput = new LogNode();
elements.auxCutMode.addEventListener = () => {};
const windows = new Map(),
    calls = [];
let keys = ['c_avg'];
const context = vm.createContext({
    document: {
        getElementById: (id) => elements[id],
        createElement: () => new LogNode(),
        createTextNode: (text) => Object.assign(new LogNode(), { textContent: text })
    },
    windows,
    loadFileList: async () => {},
    JSROOT: {
        openFile: async () => ({ fKeys: keys.map((fName) => ({ fName, fClassName: 'TCanvas' })) })
    },
    loadPlotInWindow: async (id, name, file, force) => {
        assert.equal(force, false);
        calls.push(['refresh', id]);
    },
    closePlotWindow: (id) => {
        calls.push(['close', id]);
        windows.delete(id);
    },
    createPlotWindow: (name, file, filename) => {
        const id = name;
        windows.set(id, { objectName: name, filename });
        calls.push(['create', name]);
    },
    switchToPanel: () => {
        throw new Error('Plot updates must not switch tabs automatically');
    },
    requestAnimationFrame: (f) => f(),
    setInterval: () => {},
    console
});
for (const name of ['command_builder.js', 'session_monitor.js'])
    vm.runInContext(fs.readFileSync(__dirname + '/../' + name, 'utf8'), context);
(async () => {
    context.updateCommandPreview = () => {};
    assert.ok(vm.runInContext("availableMethods('RCDAQ','single').includes('TOA/TOT')", context));
    assert.equal(
        vm.runInContext("availableMethods('RCDAQ','single').includes('TOT')", context),
        false
    );
    assert.equal(
        vm.runInContext("availableMethods('RCDAQ','single').includes('TOA')", context),
        false
    );
    for (const profile of ['NKDAQ', 'RCDAQ'])
        for (const type of ['single', 'layer', 'full', 'heatmap']) {
            if (profile === 'RCDAQ' && type === 'single') continue;
            assert.equal(
                vm.runInContext(
                    `availableMethods('${profile}','${type}').includes('TOA/TOT')`,
                    context
                ),
                false
            );
        }
    // Layer choices come from mapping geometry; AUX rows do not become layers.
    for (const id of ['moduleLabel', 'maxEventLabel', 'mappingChoices'])
        elements[id] = new LogNode();
    elements.maxEventInput.removeAttribute = () => {};
    elements.methodSelect.options = [
        'IntADC',
        'PeakADC',
        'Avg',
        'Overlay',
        'Waveform',
        'TOA/TOT'
    ].map((value) => ({ value }));
    vm.runInContext(
        "PROFILE_ENTRIES={RCDAQ:[{name:'SFIL6_xm_y0',det:0,y:0}, {name:'SFIL7_xp_y0',det:0,y:0}, {name:'Bulk1_xm_y1',det:1,y:1}, {name:'CC1',det:-1,y:-1}]}",
        context
    );
    elements.typeSelect.value = 'layer';
    vm.runInContext('updateFormFields()', context);
    assert.deepEqual(
        elements.mappingChoices.children.map((o) => o.value),
        ['Bulk_y1', 'SFIL_y0']
    );
    const firstChoice = elements.mappingChoices.children[0];
    vm.runInContext('updateFormFields()', context);
    assert.equal(
        elements.mappingChoices.children[0],
        firstChoice,
        'typing must not rebuild the suggestions'
    );
    assert.equal(vm.runInContext('TYPE_INFO.hodoscope', context), undefined);
    assert.equal(elements.moduleLabel.textContent, 'Layer (height y):');
    assert.equal(elements.methodSelect.value, 'IntADC');
    assert.ok(
        elements.methodSelect.options
            .filter((o) => ['Avg', 'Overlay', 'Waveform'].includes(o.value))
            .every((o) => o.disabled)
    );
    elements.typeSelect.value = 'single';
    elements.methodSelect.value = 'Avg';
    const oldMethod = elements.methodSelect.value,
        oldType = elements.typeSelect.value;
    elements.methodSelect.value = 'TOA/TOT';
    elements.typeSelect.value = 'single';
    elements.auxCheck.checked = true;
    elements.auxCutMode.value = 'dwc_pid';
    const direct = JSON.parse(vm.runInContext('JSON.stringify(commandRequest())', context));
    assert.equal('matched' in direct, false);
    assert.equal(direct.aux, true);
    assert.equal(direct.aux_cut_mode, 'dwc_pid');
    elements.auxCutMode.value = 'none';
    assert.equal(vm.runInContext('commandRequest().matched', context), undefined);
    elements.methodSelect.value = oldMethod;
    elements.typeSelect.value = oldType;

    vm.runInContext('setupCutControls()', context);
    assert.equal(elements.auxCutMode.disabled, false);
    for (const mode of ['none', 'dwc', 'dwc_pid']) {
        elements.auxCutMode.value = mode;
        const request = JSON.parse(vm.runInContext('JSON.stringify(commandRequest())', context));
        assert.equal(request.first, 0);
        assert.equal('matched' in request, false);
        assert.equal(request.aux_cut_mode, mode);
        assert.equal(request.profile, 'RCDAQ');
        assert.equal(request.live, true);
        assert.equal('cuts' in request, false);
        assert.equal('cut_presets' in request, false);
    }
    elements.liveMode.checked = false;
    assert.equal(vm.runInContext('sessionOptions().matched', context), undefined);
    assert.equal(vm.runInContext('sessionOptions().live', context), false);
    assert.equal(vm.runInContext('sessionOptions().aux_cut_mode', context), 'dwc_pid');
    await vm.runInContext(
        "displaySessionPlots([{name:'combined/RCDAQ/Matched/session/matched_1086.root',mtime_ns:1}])",
        context
    );
    assert.equal(windows.size, 0, 'new results must be opened by the user');
    windows.set('c_avg', {
        objectName: 'c_avg',
        filename: 'combined/RCDAQ/Matched/session/matched_1086.root'
    });
    await vm.runInContext(
        "displaySessionPlots([{name:'combined/RCDAQ/Matched/session/matched_1086.root',mtime_ns:2}])",
        context
    );
    assert.equal(windows.size, 1);
    assert.ok(calls.some((c) => c[0] === 'refresh'));
    keys = ['c_peak'];
    await vm.runInContext(
        "displaySessionPlots([{name:'combined/RCDAQ/Matched/session/matched_1086.root',mtime_ns:3}])",
        context
    );
    assert.equal(windows.size, 0, 'missing canvases close without opening new ones');
    await vm.runInContext(
        "showGeneratedFiles([{name:'raw.root',type:'root',mtime_ns:1}])",
        context
    );
    const data = {
        session: 'test',
        profile: 'RCDAQ',
        run: 1086,
        live: false,
        matching: true,
        decode: {
            status: 'running',
            matched: 1000,
            committed: 1000,
            chunks: 1,
            decoded_records: 3000,
            inputs: [{ path: '/test/input.dat', bytes: 100, records: 2 }],
            input_progress: {
                read_bytes: 200000000,
                total_bytes: 1000000000,
                files_read: 0,
                total_files: 6,
                missing_files: 0,
                percent: 20,
                complete: false
            }
        },
        analysis: { status: 'waiting_for_decode', seen: 0, chunks: 0 },
        files: []
    };
    context.fetch = async () => ({ ok: true, json: async () => structuredClone(data) });
    const rows = () => elements.commandOutput.children;
    const log = () =>
        rows()
            .map((n) => n.textContent)
            .join('\n');
    const row = (tag) => rows().find((n) => n.textContent.includes('[' + tag + ']'));
    await vm.runInContext('pollSession()', context);
    assert.match(log(), /\[Read\] 20.0% · 0.200 GB \/ 1.000 GB/);
    assert.equal(row('Input').className, 'command-info');
    assert.equal(row('Read').className, 'command-progress');
    const originalRows = rows().slice(),
        matching = row('Matching'),
        inputText = row('Input').textContent;
    const count = rows().length;
    await vm.runInContext('pollSession()', context);
    assert.equal(rows().length, count);
    data.decode.matched = 1200;
    data.decode.decoded_records = 4000;
    data.decode.inputs[0].records = 3;
    data.decode.input_progress.percent = 30;
    data.decode.input_progress.read_bytes = 300000000;
    elements.commandOutput.scrollHeight = 1000;
    elements.commandOutput.clientHeight = 100;
    elements.commandOutput.scrollTop = 100;
    await vm.runInContext('pollSession()', context);
    assert.deepEqual(rows(), originalRows, 'updates must neither add nor move progress rows');
    assert.equal(row('Matching'), matching);
    assert.match(matching.textContent, /matched 1200/);
    assert.match(row('Read').textContent, /30.0%/);
    assert.equal(row('Input').textContent, inputText);
    assert.equal(
        elements.commandOutput.scrollTop,
        100,
        'keep scroll position while reading history'
    );
    assert.equal(rows().filter((n) => n.textContent.includes('[Matching]')).length, 1);
    assert.match(matching.textContent, /^\d{2}:\d{2}:\d{2} /);
    data.decode.status = 'error';
    data.decode.error = 'incomplete input';
    await vm.runInContext('pollSession()', context);
    await vm.runInContext('pollSession()', context);
    assert.equal(rows().filter((n) => n.textContent.includes('incomplete input')).length, 1);
    assert.equal(row('Matching'), matching, 'errors must not replace progress');
    assert.ok(
        rows().findIndex((n) => n.textContent.includes('incomplete input')) <
            rows().indexOf(row('Read'))
    );
    delete data.decode.error;
    data.decode.status = 'running';
    data.decode.phase = 'matching';
    await vm.runInContext('pollSession()', context);
    assert.match(row('Decode').textContent, /matching decoded events/);
    data.decode.input_progress.complete = true;
    data.decode.input_progress.percent = 100;
    await vm.runInContext('pollSession()', context);
    assert.match(row('Decode').textContent, /input read complete; finishing matching/);
    data.decode.status = 'complete';
    data.decode.chunks = 10;
    data.analysis = {
        status: 'running',
        phase: 'reading_root',
        current_chunk: 4,
        total_chunks: 10,
        chunks: 3
    };
    await vm.runInContext('pollSession()', context);
    assert.match(
        row('Plots').textContent,
        /reading ROOT 4\/10.*total ROOT files 3\/10 \(30.0% read\)/
    );
    const plots = row('Plots');
    data.analysis.phase = 'saving_plots';
    data.analysis.chunks = 10;
    await vm.runInContext('pollSession()', context);
    assert.equal(row('Plots'), plots);
    assert.match(plots.textContent, /rendering canvases \/ saving plot file/);
    // A new session replaces the old current-status group but preserves lifecycle history.
    data.session = 'decoded';
    data.matching = false;
    data.decode.status = 'running';
    data.live = true;
    data.decode.decoded_records = 5000;
    data.decode.phase = 'collecting';
    data.analysis = { status: 'running', seen: 5000, chunks: 10 };
    elements.commandOutput.scrollTop = 900;
    await vm.runInContext('pollSession()', context);
    assert.equal(row('Matching'), undefined);
    assert.equal(row('Sync'), undefined);
    assert.match(row('Decode').textContent, /5000/);
    assert.match(row('DQM').textContent, /session test/);
    assert.equal(elements.commandOutput.scrollTop, 1000);
    const fixedRows = rows().filter((n) => n.className === 'command-progress');
    for (let i = 0; i < 2100; i++) vm.runInContext(`sessionLog('history ${i}')`, context);
    assert.equal(rows().length, 2000);
    assert.ok(
        fixedRows.every((n) => rows().includes(n)),
        'history trimming must preserve current status'
    );
    console.log(
        'Command log: fixed progress, percentages, lifecycle history, scrolling and viewer tests passed'
    );
})().catch((e) => {
    console.error(e);
    process.exitCode = 1;
});
