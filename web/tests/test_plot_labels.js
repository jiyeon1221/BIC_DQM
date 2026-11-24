const fs = require('fs'),
    vm = require('vm'),
    assert = require('assert');
const context = vm.createContext({ console, TextDecoder });
vm.runInContext(fs.readFileSync(__dirname + '/../command_builder.js', 'utf8'), context);
(async () => {
    const names = Array.from({ length: 33 }, (_, i) =>
        i < 25
            ? `SFIL${4 + Math.floor(i / 5)}_xp_y${4 - (i % 5)}`
            : `SFIL${4 + Math.floor((i - 25) / 5)}_xm_y${4 - ((i - 25) % 5)}`
    );
    let reads = 0;
    const file = {
        fKeys: [
            { fName: 'analysis_json' },
            { fName: 'c_1_draw_intADC_0', fTitle: 'NKDAQ Run 790 c_1_draw_intADC' },
            { fName: 'c_1_draw_intADC_group0_0', fTitle: 'Bulk xp · IntADC' }
        ],
        readObject: async () => {
            reads++;
            return {
                fTitle: JSON.stringify({
                    type: 'full',
                    method: 'IntADC',
                    jobs: [{}, { channels: names.concat(['Bulk1_xp_y0']) }]
                })
            };
        }
    };
    context.file = file;
    await vm.runInContext('preparePlotLabels(file)', context);
    assert.equal(
        vm.runInContext("plotKeyLabel(file,'c_1_draw_intADC_0')", context),
        'SFIL xp, SFIL xm · IntADC · 1/2'
    );
    assert.equal(
        vm.runInContext("plotKeyLabel(file,'c_1_draw_intADC_group0_0')", context),
        'Bulk xp · IntADC'
    );
    await vm.runInContext('preparePlotLabels(file)', context);
    assert.equal(reads, 1);
    assert.equal(vm.runInContext('plotLabelHtml("<Bulk & xp>")', context), '&lt;Bulk &amp; xp&gt;');
    // Real ROOT TString byte strings, as exposed by the bundled JSROOT reader.
    for (const caption of [
        'SFIL xm · Heatmap (IntADC)',
        'Bulk xp · IntADC',
        '검출기 · 파형',
        'Signal → ADC'
    ]) {
        const bytes = Buffer.from(caption, 'utf8').toString('latin1');
        context.encoded = { fKeys: [{ fName: 'canvas', fTitle: bytes }] };
        assert.equal(vm.runInContext("plotKeyLabel(encoded,'canvas')", context), caption);
        context.obj = { fTitle: bytes };
        assert.equal(vm.runInContext("plotKeyLabel(encoded,'canvas',obj)", context), caption);
        context.title = caption;
        assert.equal(vm.runInContext('rootTitleText(title)', context), caption);
    }
    for (const caption of ['Bulk1_xp_y1', 'Café · ADC', 'Â alone', '<Bulk & xp>']) {
        context.title = caption;
        assert.equal(vm.runInContext('rootTitleText(title)', context), caption);
    }
    console.log('Plot labels and ROOT title encoding: passed');
})().catch((e) => {
    console.error(e);
    process.exitCode = 1;
});
