const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
    constructor() {
        this.children = [];
        this.listeners = {};
        this.textContent = '';
    }
    appendChild(node) {
        this.children.push(node);
        return node;
    }
    append(...nodes) {
        this.children.push(...nodes);
    }
    insertBefore(node) {
        this.children.push(node);
    }
    replaceChildren(...nodes) {
        this.children = nodes;
    }
    setAttribute(name, value) {
        this[name] = value;
    }
    addEventListener(name, handler) {
        this.listeners[name] = handler;
    }
    click() {
        if (!this.disabled) return this.listeners.click?.();
    }
}
const windows = new Map(),
    timers = new Map(),
    drawn = [];
let timerId = 0;
const context = vm.createContext({
    console,
    TextDecoder,
    document: { createElement: () => new Element() },
    windows,
    setTimeout: (callback) => {
        timers.set(++timerId, callback);
        return timerId;
    },
    clearTimeout: (id) => timers.delete(id),
    JSROOT: {
        cleanup: () => {},
        draw: async (_, object) => {
            drawn.push(object.fName);
        }
    }
});
for (const file of ['command_builder.js', 'waveform_viewer.js']) {
    vm.runInContext(fs.readFileSync(__dirname + '/../' + file, 'utf8'), context);
}
// Exercise the same dispatch used by plot clicks and manual refresh in the page.
const html = fs.readFileSync(__dirname + '/../index.html', 'utf8');
vm.runInContext(
    html.slice(
        html.indexOf('function loadPlotInWindow('),
        html.indexOf('function loadPlotFromFile(')
    ),
    context
);
const key = (event, group = 0, title = 'Bulk1_xp_y1') => ({
    fName: `c_Waveform_${event}_group${group}_0`,
    fClassName: 'TCanvas',
    fTitle: `${title} · Waveform · Event ${event}`
});
function rootFile(keys) {
    return { fKeys: keys, readObject: async (name) => keys.find((k) => k.fName === name) };
}
function openWindow(id, file, name = file.fKeys[0].fName) {
    const body = new Element(),
        title = new Element(),
        handle = new Element(),
        element = new Element();
    element.querySelector = (selector) =>
        ({
            '.plot-window-body': body,
            '.plot-window-title': title,
            '.plot-window-resize-handle': handle
        })[selector];
    const data = { element, objectName: name, rootFile: file, filename: 'waveform.root' };
    windows.set(id, data);
    return data;
}
const flush = async () => {
    for (let i = 0; i < 12; ++i) await Promise.resolve();
};
const tick = async () => {
    assert.equal(timers.size, 1);
    const [id, callback] = [...timers][0];
    timers.delete(id);
    await callback();
    await flush();
};

(async () => {
    const file = rootFile([
        key(10),
        key(9),
        key(11, 1, 'Bulk1_xm_y1'),
        key(12),
        { fName: 'c_AUX', fClassName: 'TCanvas', fTitle: 'DWC1, DWC2' }
    ]);
    const series = context.waveformSeries(file);
    assert.equal(series.length, 2);
    assert.deepEqual(
        Array.from(series[0].frames, (f) => f.event),
        ['9', '10', '12']
    );
    assert.equal(
        context.waveformSidebarKeys(file).length,
        3,
        'one entry per waveform group plus AUX'
    );
    assert.equal(
        context.waveformSidebarLabel(file, key(9).fName),
        'Bulk1_xp_y1 · Waveform · 3 events'
    );
    // A missing channel group may change its numeric group ID between events.
    assert.equal(context.waveformSeries(rootFile([key(1, 0), key(2, 1)])).length, 1);
    const data = openWindow('one', file, key(9).fName);
    await context.loadPlotInWindow('one', key(9).fName, file);
    const controls = data.waveform.controls;
    assert.equal(windows.size, 1);
    assert.equal(controls.label.textContent, '1 / 3');
    assert.equal(controls.previous.disabled, true);
    await controls.next.click();
    assert.equal(data.objectName, key(10).fName);
    assert.equal(controls.label.textContent, '2 / 3');
    controls.slider.value = '2';
    await controls.slider.listeners.input();
    assert.equal(data.objectName, key(12).fName);
    assert.equal(controls.next.disabled, true);
    controls.play.click();
    await flush(); // Play from the end starts at the first frame.
    assert.equal(data.objectName, key(9).fName);
    await tick();
    assert.equal(data.objectName, key(10).fName);
    controls.play.click();
    assert.equal(timers.size, 0, 'Pause cancels playback');
    controls.play.click();
    await tick();
    assert.equal(data.objectName, key(12).fName);
    assert.equal(data.waveform.playing, false, 'stop at the last event');
    assert.equal(windows.size, 1, 'navigation never opens additional windows');
    const liveFile = rootFile([key(9), key(10), key(12), key(13)]);
    await context.loadPlotInWindow('one', data.objectName, liveFile);
    assert.equal(data.objectName, key(12).fName, 'live snapshots preserve the selected event');
    assert.equal(controls.label.textContent, '3 / 4');
    assert.equal(controls.next.disabled, false);
    context.JSROOT.openFile = async () => liveFile;
    await context.loadPlotInWindow('one', data.objectName, file, true);
    assert.equal(data.rootFile, liveFile, 'refresh loads the new snapshot');

    let release;
    const delayedFile = rootFile([key(1), key(2)]);
    delayedFile.readObject = () =>
        new Promise((resolve) => {
            release = resolve;
        });
    const pending = openWindow('pending', delayedFile);
    const loading = context.loadPlotInWindow('pending', key(1).fName, delayedFile);
    assert.equal(pending.waveform.controls.next.disabled, true);
    const newer = rootFile([key(1), key(2), key(3)]);
    const before = drawn.length;
    context.loadPlotInWindow('pending', key(1).fName, newer);
    release({ fName: 'obsolete' });
    await loading;
    assert.deepEqual(
        drawn.slice(before),
        [key(1).fName],
        'stale reads cannot overwrite newer snapshots'
    );
    context.disposeWaveformWindow(pending);
    windows.delete('pending');

    const closing = openWindow('closing', delayedFile);
    const closingRead = context.loadPlotInWindow('closing', key(1).fName, delayedFile);
    const count = drawn.length;
    context.disposeWaveformWindow(closing);
    windows.delete('closing');
    release(key(1));
    await closingRead;
    assert.equal(drawn.length, count, 'closed windows cannot draw after pending reads finish');
    controls.play.click();
    await flush();
    context.disposeWaveformWindow(data);
    windows.delete('one');
    assert.equal(timers.size, 0, 'closing cancels playback timers');
    console.log(
        'Waveform grouping, navigation, playback, live refresh, stale reads and close: passed'
    );
})().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
