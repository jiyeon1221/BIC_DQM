#include "plot_common.h"

namespace DQMPlot {
// Draw selected raw ADC waveforms in detector coordinates.
void draw_waveform(Plots& p) {
    for (auto& frame : p.frames) {
        size_t group = 0;
        for (auto& g : p.groups(frame.names)) {
            Items items;
            std::vector<std::unique_ptr<TGraph>> graphs;
            for (auto& name : g.second) {
                auto& wave = frame.waves.at(name);
                int start = p.row(name).daq == "GCROC" ? 1 : 0;
                auto graph = std::make_unique<TGraph>(std::max(0, int(wave.size()) - start));
                for (size_t i = start; i < wave.size(); ++i)
                    graph->SetPoint(i - start, double(i), wave[i]);
                graph->SetName(("wave_" + std::to_string(frame.event) + "_" + name).c_str());
                graph->SetTitle((name + " " + frame.label + ";Sample index;ADC (raw)").c_str());
                items.push_back({graph.get(), "AL"});
                graphs.push_back(std::move(graph));
            }
            p.panels("c_Waveform_" + std::to_string(frame.event) + "_group" +
                         std::to_string(group++),
                     items, g.first + " · Waveform · " + frame.label, g.second);
        }
    }
}
}
