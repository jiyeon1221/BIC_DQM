#include "plot_common.h"

namespace DQMPlot {
// Plot coincident DWC positions, correlations, and CC PeakADC.
TH2D* Plots::derivedHist(const std::string& name) {
    Key key{"derived", name};
    auto i = hists.find(key);
    if (i != hists.end())
        return static_cast<TH2D*>(i->second.get());
    auto title = name.rfind("DWC", 0) == 0 ? name + ";x [mm];y [mm]"
                                           : "DWC correlation;DWC1 " +
            name.substr(name.size() - 1) + " [mm];DWC2 " + name.substr(name.size() - 1) + " [mm]";
    auto* h = new TH2D(("h_" + name).c_str(), title.c_str(), 120, -60, 60, 120, -60, 60);
    h->SetDirectory(nullptr);
    hists[key].reset(h);
    return h;
}

void fill_aux(Plots& p, const Job& job, const Input& e, std::set<std::string>& filled,
              const std::function<bool(const Key&)>& take, bool& used) {
    for (int d = 0; d < 2; ++d) {
        auto name = "DWC" + std::to_string(d + 1);
        double x = e.derived->at(2 * d), y = e.derived->at(2 * d + 1);
        if (!filled.count(name) && std::isfinite(x) && std::isfinite(y) &&
            take({"derived", name})) {
            used = true;
            p.derivedHist(name)->Fill(x, y);
            filled.insert(name);
        }
    }
    if (p.matching)
        for (int a = 0; a < 2; ++a) {
            std::string name = a == 0 ? "CorrX" : "CorrY";
            double x = e.derived->at(a), y = e.derived->at(a + 2);
            if (!filled.count(name) && std::isfinite(x) && std::isfinite(y) &&
                take({"derived", "Corr" + std::to_string(a)})) {
                used = true;
                p.derivedHist(name)->Fill(x, y);
                filled.insert(name);
            }
        }
    if (job.executable == "draw_AUX")
        for (auto& name : job.channels) {
            auto i = p.index.at(name);
            if (name.rfind("CC", 0) == 0 && e.usable->at(i) && !filled.count(name) &&
                take({name, "PeakADC"})) {
                used = true;
                p.hist(name, "PeakADC")->Fill(e.peak->at(i));
                filled.insert(name);
            }
        }
}

void draw_aux(Plots& p, const Job& job, size_t number) {
    Items items;
    for (auto name : {"DWC1", "DWC2"})
        items.push_back({p.derivedHist(name), "COLZ"});
    if (p.matching)
        for (auto name : {"CorrX", "CorrY"})
            items.push_back({p.derivedHist(name), "COLZ"});
    std::string title = "DWC1, DWC2";
    if (job.executable == "draw_AUX")
        for (auto& name : job.channels)
            if (name.rfind("CC", 0) == 0) {
                title += ", " + name;
                items.push_back({p.hist(name, "PeakADC"), "HIST"});
            }
    p.panels("c_" + std::to_string(number) + "_" + job.executable, items, title);
}
}
