#include "plot_common.h"

namespace DQMPlot {
// Display each channel's mean ADC metric at its physical z/y position.
void fill_heatmap(Plots& p, size_t i, double value) {
    p.sums[i] += value;
    ++p.counts[i];
}

void draw_heatmap(Plots& p, const Job& job, size_t number) {
    std::set<std::pair<int, int>> regions;
    std::vector<size_t> selected;
    for (size_t i = 0; i < p.rows.size(); ++i)
        if (std::find(job.channels.begin(), job.channels.end(), p.rows[i].name) !=
            job.channels.end()) {
            selected.push_back(i);
            regions.insert({p.rows[i].det, p.rows[i].side});
        }
    for (auto [det, side] : regions) {
        int nz = 0, ny = 0;
        std::vector<size_t> rows;
        for (auto i : selected)
            if (p.rows[i].det == det && p.rows[i].side == side) {
                rows.push_back(i);
                nz = std::max(nz, p.rows[i].z + 1);
                ny = std::max(ny, p.rows[i].y + 1);
            }
        std::string region = std::string(det == 0 ? "SFIL" : "Bulk") + (side == 0 ? " xm" : " xp"),
                    suffix = std::to_string(number) + "_" + std::to_string(det) + "_" +
            std::to_string(side);
        TH2D h(("map_" + suffix).c_str(), (region + ";z;y;Mean " + p.method).c_str(), nz, -.5,
               nz - .5, ny, -.5, ny - .5);
        h.SetDirectory(nullptr);
        h.SetStats(false);
        std::map<std::pair<int, int>, double> sums;
        std::map<std::pair<int, int>, ULong64_t> counts;
        for (auto i : rows) {
            auto& r = p.rows[i];
            h.GetXaxis()->SetBinLabel(r.z + 1, r.module.c_str());
            auto key = std::make_pair(r.z + 1, r.y + 1);
            sums[key] += p.sums[i];
            counts[key] += p.counts[i];
        }
        for (int y = 0; y < ny; ++y)
            h.GetYaxis()->SetBinLabel(y + 1, ("y" + std::to_string(y)).c_str());
        h.GetXaxis()->SetTitle("Module (+z)");
        for (auto [key, sum] : sums)
            if (counts[key])
                h.SetBinContent(key.first, key.second, sum / counts[key]);
        p.panels("c_" + std::to_string(number) + "_" + job.executable + "_" + std::to_string(det) +
                     "_" + std::to_string(side),
                 {{&h, "COLZ TEXT"}}, region + " · Heatmap (" + p.method + ")");
    }
}
}
